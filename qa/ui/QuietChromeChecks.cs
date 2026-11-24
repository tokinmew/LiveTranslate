using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using LiveTranslate;

// Isolated native controls only. No application worker, capture or user files.
internal static class QuietChromeChecks
{
    [StructLayout(LayoutKind.Sequential)] struct NativeRect { internal int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] struct ScrollBarInfo
    {
        internal int Size; internal NativeRect Rectangle; internal int ArrowSize, ThumbTop, ThumbBottom, Reserved;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 6)] internal uint[] States;
    }
    [DllImport("user32.dll")] static extern bool GetScrollBarInfo(IntPtr window, int id, ref ScrollBarInfo info);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window, out NativeRect rectangle);
    [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr window, IntPtr dc, uint flags);
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wp, IntPtr lp);
    static int checks;
    static void Check(bool value, string message) { if (!value) throw new Exception(message); checks++; Console.WriteLine("PASS " + message); }
    static Bitmap Snapshot(Control control)
    {
        control.Refresh(); Application.DoEvents();
        Bitmap image = new Bitmap(control.Width, control.Height);
        bool rendered;
        using (Graphics graphics = Graphics.FromImage(image))
        {
            IntPtr dc = graphics.GetHdc();
            try { rendered = PrintWindow(control.Handle, dc, 0); }
            finally { graphics.ReleaseHdc(dc); }
        }
        if (!rendered)
        {
            image.Dispose();
            Form form = control.FindForm();
            if (form == null || form == control) throw new Exception("Native rendering failed");
            NativeRect root, child; GetWindowRect(form.Handle, out root); GetWindowRect(control.Handle, out child);
            using (Bitmap full = Snapshot(form))
                return full.Clone(new Rectangle(child.Left - root.Left, child.Top - root.Top, control.Width, control.Height), PixelFormat.Format32bppArgb);
        }
        return image;
    }
    static Rectangle NativeBar(Control control)
    {
        ScrollBarInfo info = new ScrollBarInfo { Size = Marshal.SizeOf(typeof(ScrollBarInfo)), States = new uint[6] };
        NativeRect window;
        Check(GetWindowRect(control.Handle, out window) && GetScrollBarInfo(control.Handle, -5, ref info) && (info.States[0] & 0x8000) == 0,
            "A real native vertical scrollbar remains present");
        return Rectangle.FromLTRB(info.Rectangle.Left - window.Left, info.Rectangle.Top - window.Top,
            info.Rectangle.Right - window.Left, info.Rectangle.Bottom - window.Top);
    }
    static void CheckBar(Control control, string label, string folder)
    {
        Rectangle bar = NativeBar(control);
        using (Bitmap image = Snapshot(control))
        {
            Rectangle sample = Rectangle.Intersect(bar, new Rectangle(Point.Empty, image.Size));
            int bright = 0, total = 0;
            for (int y = sample.Top; y < sample.Bottom; y++) for (int x = sample.Left; x < sample.Right; x++)
            { Color pixel = image.GetPixel(x, y); total++; if (pixel.R > 210 && pixel.G > 210 && pixel.B > 210) bright++; }
            Check(total > 30 && bright < total / 20, label + " scrollbar paints a quiet dark track and thumb");
            image.Save(Path.Combine(folder, label + "-scrollbar.png"), ImageFormat.Png);
        }
    }
    static bool Command(TabControl tabs, Keys keys)
    {
        MethodInfo command = tabs.GetType().GetMethod("ProcessCmdKey", BindingFlags.Instance | BindingFlags.NonPublic);
        object[] args = { Message.Create(tabs.Handle, 0x100, IntPtr.Zero, IntPtr.Zero), keys };
        return (bool)command.Invoke(tabs, args);
    }
    [STAThread] static int Main(string[] args)
    {
        try
        {
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            string folder = args[0]; Directory.CreateDirectory(folder);
            using (Form form = new Form { ClientSize = new Size(720, 590), ShowInTaskbar = false,
                StartPosition = FormStartPosition.Manual, Location = new Point(SystemInformation.VirtualScreen.Right + 200, 0), BackColor = WindowTheme.Background })
            using (ThemedTabControl tabs = new ThemedTabControl { Bounds = new Rectangle(10, 10, 700, 285), Padding = new Point(10, 7), Font = new Font("Segoe UI", 10F) })
            using (RichTextBox rich = new RichTextBox { Bounds = new Rectangle(10, 310, 345, 265), BorderStyle = BorderStyle.None,
                ReadOnly = true, BackColor = WindowTheme.Card, ForeColor = WindowTheme.Ink, Font = new Font("Segoe UI", 11F) })
            using (Panel page = new Panel { Bounds = new Rectangle(370, 310, 340, 265), BackColor = WindowTheme.Card, AutoScroll = true })
            {
                foreach (string title in new[] { "Audio and screen", "Language files", "Updates", "Spoken English" })
                    tabs.TabPages.Add(new TabPage(title) { BackColor = WindowTheme.Card, ForeColor = WindowTheme.Ink });
                form.Controls.Add(tabs); form.Controls.Add(rich); form.Controls.Add(page);
                page.Controls.Add(new Label { Text = "Scrollable fixture", Location = new Point(10, 650), AutoSize = true, ForeColor = WindowTheme.Ink });
                for (int line = 0; line < 150; line++) rich.AppendText("Line " + line + ": selectable fixture text.\n");
                QuietScrollbars.Attach(rich); QuietScrollbars.Attach(page);
                for (int repeat = 0; repeat < 100; repeat++) { QuietScrollbars.Attach(rich); QuietScrollbars.Attach(page); }
                form.Show(); Application.DoEvents();
                Check(!form.Bounds.IntersectsWith(SystemInformation.VirtualScreen), "Native fixture remains outside visible displays");
                Check(tabs.TabCount == 4 && tabs.SelectedIndex == 0, "Native tab pages and selected index are retained");
                int selectedEvents = 0; tabs.SelectedIndexChanged += delegate { selectedEvents++; };
                tabs.SelectedIndex = 2;
                Check(selectedEvents == 1 && tabs.SelectedTab.Text == "Updates", "Programmatic selection dispatches the native selection event once");
                Check(Command(tabs, Keys.Control | Keys.Tab) && tabs.SelectedIndex == 3, "Control Tab advances the native selected page");
                Check(Command(tabs, Keys.Control | Keys.Shift | Keys.Tab) && tabs.SelectedIndex == 2, "Control Shift Tab returns to the previous page");
                using (Bitmap image = Snapshot(tabs))
                {
                    Color frame = image.GetPixel(1, tabs.DisplayRectangle.Top + 20);
                    Color blankHeader = image.GetPixel(tabs.Width - 10, 10);
                    Check(frame.GetBrightness() < .4F && blankHeader.GetBrightness() < .4F, "Tab page frame and unused header band have no bright native chrome");
                    image.Save(Path.Combine(folder, "settings-tabs.png"), ImageFormat.Png);
                }
                rich.Select(0, 4); rich.ScrollToCaret();
                int before = SendMessage(rich.Handle, 0xCE, IntPtr.Zero, IntPtr.Zero).ToInt32();
                SendMessage(rich.Handle, 0x115, new IntPtr(1), IntPtr.Zero);
                int after = SendMessage(rich.Handle, 0xCE, IntPtr.Zero, IntPtr.Zero).ToInt32();
                Check(after > before && rich.SelectedText == "Line", "Native line scrolling moves the rich text without disturbing selection");
                CheckBar(rich, "rich-text", folder);
                page.AutoScrollPosition = new Point(0, 200);
                Check(page.AutoScrollPosition.Y == -200, "Panel retains its native scrolling position contract");
                CheckBar(page, "panel", folder);
                typeof(Control).GetMethod("RecreateHandle", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(rich, null);
                Application.DoEvents(); CheckBar(rich, "recreated-rich-text", folder);
                Check(rich.SelectedText == "Line", "Recreating the themed HWND retains the native text selection");
                using (Bitmap image = Snapshot(form)) image.Save(Path.Combine(folder, "quiet-chrome.png"), ImageFormat.Png);
                Console.WriteLine(checks + " quiet chrome checks passed.");
            }
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
