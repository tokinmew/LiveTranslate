using System;
using System.Collections;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal static class CheckTranscript
{
    const BindingFlags Private = BindingFlags.NonPublic | BindingFlags.Instance;
    [DllImport("user32.dll")] static extern int GetGuiResources(IntPtr process, int kind);
    [DllImport("user32.dll", CharSet=CharSet.Auto)]
    static extern IntPtr SendMessage(IntPtr window, int message, IntPtr w, IntPtr l);
    static void Check(bool value, string detail)
    {
        if (!value) throw new InvalidOperationException(detail);
        Console.WriteLine("PASS " + detail);
    }
    static T Field<T>(Form window, string name)
    {
        return (T)window.GetType().GetField(name, Private).GetValue(window);
    }
    static string Marker(int i) { return "[line-" + i.ToString("D5") + "]"; }
    static int Top(RichTextBox box)
    {
        return SendMessage(box.Handle, 0xCE, IntPtr.Zero, IntPtr.Zero).ToInt32();
    }
    static string TopText(RichTextBox box)
    {
        int start = box.GetFirstCharIndexFromLine(Top(box));
        return box.Text.Substring(start, Math.Min(60, box.TextLength - start));
    }
    static int Resources(int kind)
    {
        using (Process process = Process.GetCurrentProcess()) return GetGuiResources(process.Handle, kind);
    }
    [STAThread] public static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        var type = Assembly.LoadFrom(Path.GetFullPath(args[0])).GetType("LiveTranslate.MainForm", true);
        using (var form = (Form)Activator.CreateInstance(type, true))
        {
            var box = Field<RichTextBox>(form, "output");
            var show = Field<CheckBox>(form, "showSource");
            var history = Field<IList>(form, "history");
            var append = type.GetMethod("AddCaption", Private);
            Action<int> add = delegate(int i) {
                append.Invoke(form, new object[]{"Screen", Marker(i) + " The next train arrives at four.",
                    "次の列車は四時に到着します。"});
            };
            // Create native controls without showing MainForm or running its capture startup.
            IntPtr handle = form.Handle;
            handle = box.Handle;
            box.Size = new Size(650,290);
            for (int i = 0; i < 180; ++i) add(i);
            Check(Top(box) > 0, "Live output follows the latest arrival");
            int selected = box.Text.IndexOf(Marker(119), StringComparison.Ordinal);
            box.Select(selected, Marker(119).Length);
            box.ScrollToCaret();
            string before = TopText(box);
            add(180);
            Check(box.SelectedText == Marker(119), "Selection survives a new caption and oldest-entry eviction");
            Check(before == TopText(box), "The visible line stays in place while reading a selection");
            show.Checked = false;
            Check(box.SelectedText == Marker(119), "Reading the same entry survives hiding all older source lines");
            show.Checked = true;
            Check(box.SelectedText == Marker(119), "Showing source again preserves the selected translation");
            box.Select(box.TextLength, 0);
            box.ScrollToCaret();
            SendMessage(box.Handle, 0xB6, IntPtr.Zero, new IntPtr(-36));
            before = TopText(box);
            add(181);
            Check(before == TopText(box), "Scrolling back without selecting text also holds the reading position");
            box.Select(box.TextLength, 0);
            box.ScrollToCaret();
            show.Checked = false;
            Check(!box.Text.Contains("次の列車"), "Hiding the source rerenders the transcript");
            show.Checked = true;
            Check(box.Text.Contains("次の列車"), "Original glyphs return when source text is enabled");
            int gdi = Resources(0), user = Resources(1);
            var timer = Stopwatch.StartNew();
            for (int i = 182; i < 1182; ++i)
            {
                if (i % 100 == 0) form.Size = new Size(i % 200 == 0 ? 840 : 1200, 740);
                add(i);
            }
            timer.Stop();
            string text = box.Text;
            Check(history.Count == 180 && text.Contains(Marker(1002)) && text.Contains(Marker(1181)) &&
                !text.Contains(Marker(1001)), "Only the latest 180 captions remain after 1,182 deliveries");
            int gdiChange = Resources(0) - gdi, userChange = Resources(1) - user;
            Console.WriteLine("1000 appends in {0} ms. GDI delta {1}, USER delta {2}.",
                timer.ElapsedMilliseconds, gdiChange, userChange);
            Check(gdiChange < 60 && userChange < 20, "Native handle counts remain bounded during the burst");
            box.Select(8, 12);
            history.Clear();
            type.GetMethod("RenderCaptions", Private).Invoke(form, null);
            Check(box.TextLength == 0 && box.SelectionLength == 0, "Clearing the transcript drops the previous selection");
            Check(!form.Visible && Field<object>(form, "worker") == null, "The test kept every capture input closed");
        }
    }
}
