using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using LiveTranslate;

// Isolated app-owned HWNDs only; never starts capture or opens user documents.
internal static class ThemedInputChecks
{
    [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] private struct ComboInfo
    {
        public int Size; public Rect Item, Button; public int ButtonState; public IntPtr Combo, Edit, List;
    }
    [DllImport("user32.dll")] private static extern bool PrintWindow(IntPtr window, IntPtr dc, uint flags);
    [DllImport("user32.dll")] private static extern bool GetComboBoxInfo(IntPtr window, ref ComboInfo info);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr window, out Rect rect);
    [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wp, IntPtr lp);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr window, int mode);
    private static int passed;
    private static void Check(bool value, string name)
    {
        if (!value) throw new InvalidOperationException(name);
        passed++; Console.WriteLine("PASS " + name);
    }
    private sealed class FixtureWindow : Form
    {
        protected override bool ShowWithoutActivation { get { return true; } }
    }
    private static Bitmap Capture(Control control)
    {
        Bitmap bitmap = new Bitmap(control.Width, control.Height);
        using (Graphics graphics = Graphics.FromImage(bitmap))
        {
            IntPtr dc = graphics.GetHdc();
            try
            {
                if (!PrintWindow(control.Handle, dc, 0)) SendMessage(control.Handle, 0x317, dc, new IntPtr(30));
            }
            finally { graphics.ReleaseHdc(dc); }
        }
        return bitmap;
    }
    private static double Brightness(Color color) { return (color.R + color.G + color.B) / 3.0; }
    private static void CheckField(Control control, string name, string output)
    {
        using (Bitmap bitmap = Capture(control))
        {
            Check(Brightness(bitmap.GetPixel(Math.Max(1, bitmap.Width - 3), bitmap.Height - 3)) < 100, name + " field background stays dark");
            int ink = 0;
            for (int y = 1; y < bitmap.Height - 1; y++)
                for (int x = 1; x < bitmap.Width - 1; x++)
                    if (Brightness(bitmap.GetPixel(x, y)) > 105) ink++;
            Check(ink > 3, name + " retains visible text or arrow glyphs");
            bitmap.Save(Path.Combine(output, name + ".png"), ImageFormat.Png);
        }
    }
    [STAThread] private static int Main(string[] args)
    {
        try
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string output = args.Length > 0 ? args[0] : Path.Combine(Path.GetTempPath(), "LiveTranslate-input-check");
            Directory.CreateDirectory(output);
            using (var window = new FixtureWindow { Size = new Size(480, 260), BackColor = WindowTheme.Card,
                StartPosition = FormStartPosition.Manual, Location = new Point(SystemInformation.VirtualScreen.Right + 300, 0), ShowInTaskbar = false })
            using (var combo = new ThemedComboBox { Bounds = new Rectangle(20, 20, 390, 28), Font = new Font("Segoe UI", 10F), FlatStyle = FlatStyle.Standard, AccessibleName = "Fixture audio device" })
            using (var number = new ThemedNumericUpDown { Bounds = new Rectangle(20, 75, 100, 28), Minimum = 1, Maximum = 8, Value = 3, AccessibleName = "Fixture CPU threads" })
            using (var input = new ThemedTextBox { Bounds = new Rectangle(20, 120, 390, 26), Text = "Selectable text", BackColor = WindowTheme.Field, ForeColor = WindowTheme.Ink, BorderStyle = BorderStyle.FixedSingle, AccessibleName = "Fixture text" })
            {
                combo.Items.AddRange(new object[] { "Computer audio · Default playback", "Microphone · Selected device", "Both inputs" });
                combo.SelectedIndex = 0;
                window.Controls.Add(combo); window.Controls.Add(number); window.Controls.Add(input);
                window.Show(); Application.DoEvents();
                Check(!window.Bounds.IntersectsWith(SystemInformation.VirtualScreen), "Input fixture stays outside visible displays");
                Check(combo is ComboBox && number is NumericUpDown && input is TextBox, "Themed fields preserve native control types and APIs");
                Check(!String.IsNullOrEmpty(combo.AccessibleName) && combo.TabStop && number.TabStop && input.TabStop, "Native fields retain accessibility labels and tab access");
                CheckField(combo, "combo-enabled", output);
                int changed = 0; combo.SelectedIndexChanged += delegate { changed++; };
                SendMessage(combo.Handle, 0x100, new IntPtr((int)Keys.Down), IntPtr.Zero);
                SendMessage(combo.Handle, 0x101, new IntPtr((int)Keys.Down), IntPtr.Zero);
                Application.DoEvents();
                Check(combo.SelectedIndex == 1 && changed == 1, "Native Down key changes the selection once");
                combo.Enabled = false; Application.DoEvents();
                CheckField(combo, "combo-disabled", output);
                Check(combo.SelectedIndex == 1, "Disabling a field preserves its selected device");
                combo.Enabled = true;
                CheckField(number, "number-enabled", output);
                int values = 0; number.ValueChanged += delegate { values++; };
                number.UpButton(); number.DownButton();
                Check(number.Value == 3 && values == 2, "Native numeric up and down retain ValueChanged semantics");
                number.Value = number.Maximum; number.UpButton();
                Check(number.Value == number.Maximum, "Native spinner respects the maximum");
                number.Value = number.Minimum; number.DownButton();
                Check(number.Value == number.Minimum, "Native spinner respects the minimum");
                Control spinner = null;
                foreach (Control child in number.Controls) if (child.GetType().Name == "UpDownButtons") spinner = child;
                Check(spinner != null, "The existing native repeat-button control is retained");
                CheckField(spinner, "numeric-buttons", output);
                number.Enabled = false; Application.DoEvents();
                CheckField(spinner, "numeric-buttons-disabled", output);
                number.Enabled = true;
                CheckField(input, "text-outline", output);
                input.ReadOnly = true; input.Select(0, 10);
                Check(input.SelectedText == "Selectable", "Read-only native text remains selectable");
                input.BorderStyle = BorderStyle.None;
                CheckField(input, "text-borderless", output);
                Check(input.BorderStyle == BorderStyle.None, "Caller-requested borderless fields remain borderless");

                combo.MaxDropDownItems = 2;
                combo.DroppedDown = true; Application.DoEvents();
                ComboInfo info = new ComboInfo(); info.Size = Marshal.SizeOf(typeof(ComboInfo));
                Check(GetComboBoxInfo(combo.Handle, ref info) && info.List != IntPtr.Zero, "Combo dropdown remains a native list HWND");
                Rect bounds; GetWindowRect(info.List, out bounds);
                // Windows can reposition a popup onto a monitor. Hide only this
                // fixture-owned list in that case; its independent HWND still renders.
                if (new Rectangle(bounds.Left, bounds.Top, bounds.Right - bounds.Left, bounds.Bottom - bounds.Top).IntersectsWith(SystemInformation.VirtualScreen))
                    ShowWindow(info.List, 0);
                using (var bitmap = new Bitmap(Math.Max(1, bounds.Right - bounds.Left), Math.Max(1, bounds.Bottom - bounds.Top)))
                using (Graphics graphics = Graphics.FromImage(bitmap))
                {
                    IntPtr dc = graphics.GetHdc();
                    try { Check(PrintWindow(info.List, dc, 0), "Native dropdown renders independently of the closed field"); }
                    finally { graphics.ReleaseHdc(dc); }
                    bitmap.Save(Path.Combine(output, "combo-open-list.png"), ImageFormat.Png);
                    Check(Brightness(bitmap.GetPixel(bitmap.Width / 2, 4)) < 100, "Open native dropdown rows retain the dark fill");
                    Check(Brightness(bitmap.GetPixel(0, 0)) < 100, "Native popup outline stays within the quiet palette");
                }
                combo.DroppedDown = false;
                Check(combo.SelectedIndex == 1, "Opening and closing the popup preserves selection");
                window.Hide();
            }
            Console.WriteLine(passed + " themed input checks passed.");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
