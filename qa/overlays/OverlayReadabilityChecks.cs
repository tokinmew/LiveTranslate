using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal static class OverlayReadabilityChecks
    {
        [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr hwnd, IntPtr dc, uint flags);
        [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll", EntryPoint = "SendMessageW")] static extern IntPtr SendMessage(IntPtr hwnd, int message, IntPtr w, IntPtr l);
        static int checks;

        static void Verify(bool ok, string description)
        {
            if (!ok) throw new Exception(description);
            Console.WriteLine("PASS " + description);
            checks++;
        }

        static T Named<T>(Control root, string name) where T : Control
        {
            if (root is T && root.AccessibleName == name) return (T)root;
            foreach (Control child in root.Controls)
            {
                T match = Named<T>(child, name);
                if (match != null) return match;
            }
            return null;
        }

        static void SaveWindow(Form form, string path)
        {
            form.Refresh();
            Application.DoEvents();
            using (var bitmap = new Bitmap(form.ClientSize.Width, form.ClientSize.Height))
            using (var graphics = Graphics.FromImage(bitmap))
            {
                IntPtr dc = graphics.GetHdc();
                try { Verify(PrintWindow(form.Handle, dc, 3), "Rendered the synthetic caption window: " + Path.GetFileName(path)); }
                finally { graphics.ReleaseHdc(dc); }
                bitmap.Save(path, ImageFormat.Png);
            }
        }

        static int FirstLine(RichTextBox body)
        {
            return SendMessage(body.Handle, 0x00CE, IntPtr.Zero, IntPtr.Zero).ToInt32();
        }

        static void CheckVr(string output)
        {
            var state = new VrCaptionState();
            using (var window = new VrCaptionWindow(state))
            {
                window.Location = new Point(-23000, -23000);
                window.Show();
                Application.DoEvents();
                var filter = Named<ComboBox>(window, "Caption source");
                var screen = Named<RichTextBox>(window, "Screen translation");
                var position = Named<Label>(window, "Screen reading position");
                var empty = window.Controls.OfType<Panel>().SelectMany(p => p.Controls.OfType<Label>()).First(l => l.Dock == DockStyle.Fill);
                filter.SelectedIndex = 2;
                Verify(empty.Visible && empty.Text.Contains("screen captions"), "Filtered empty state names the selected source");
                filter.SelectedIndex = 0;
                string paragraph = String.Join(" ", Enumerable.Repeat("Follow the signs to the west platform.", 18).ToArray());
                state.Present("screen", paragraph, VrCaptionWindow.Clock.ElapsedMilliseconds);
                state.Present("audio", "The next train arrives in three minutes.", VrCaptionWindow.Clock.ElapsedMilliseconds);
                state.Present("text", "Exit on the left.", VrCaptionWindow.Clock.ElapsedMilliseconds);
                window.RefreshCaptions();
                Application.DoEvents();
                Verify(screen.Text == paragraph && FirstLine(screen) == 0 && position.Text.StartsWith("Lines 1"), "Overflow opens at the first line with the complete caption selectable");
                SaveWindow(window, Path.Combine(output, "vr-sources.png"));
                var advance = typeof(VrCaptionWindow).GetMethod("UpdatePage", BindingFlags.NonPublic | BindingFlags.Instance);
                long clock = VrCaptionWindow.Clock.ElapsedMilliseconds;
                IntPtr foreground = GetForegroundWindow();
                List<int> starts = new List<int> { FirstLine(screen) };
                for (int i = 0; i < 100; i++)
                {
                    clock += 20000;
                    int delay = (int)advance.Invoke(window, new object[] { 1, clock });
                    starts.Add(FirstLine(screen));
                    if (delay == 0) break;
                }
                Verify(starts.Count > 2 && starts.Count < 101 && starts[starts.Count - 1] > 0 && starts.SequenceEqual(starts.OrderBy(v => v)), "Hands-free reading advances through the caption and stops on its last page");
                string[] lastPosition = position.Text.Split(' ');
                string[] shownRange = lastPosition[1].Split('–');
                int finalShown = Int32.Parse(shownRange[shownRange.Length - 1]);
                Verify(finalShown == Int32.Parse(lastPosition[3]), "The final wrapped line is visible before paging stops");
                Verify(GetForegroundWindow() == foreground && screen.Text == paragraph, "Automatic paging preserves foreground focus and the source text");
                string lastRange = position.Text;
                int lastStart = FirstLine(screen);
                state.Present("screen", paragraph, VrCaptionWindow.Clock.ElapsedMilliseconds);
                window.RefreshCaptions();
                Verify(FirstLine(screen) == lastStart && position.Text == lastRange, "A duplicate screen caption leaves the final page in place");
                state.Present("screen", paragraph + " Continue outside.", VrCaptionWindow.Clock.ElapsedMilliseconds);
                window.RefreshCaptions();
                Verify(FirstLine(screen) == 0 && position.Text.StartsWith("Lines 1"), "New text begins at the top after a long previous caption");
                typeof(Control).GetMethod("OnMouseDown", BindingFlags.NonPublic | BindingFlags.Instance).Invoke(screen,
                    new object[] { new MouseEventArgs(MouseButtons.Left, 1, 8, 8, 0) });
                advance.Invoke(window, new object[] { 1, clock + 30000 });
                Verify(FirstLine(screen) == 0, "Mouse interaction hands reading position back to the user");
                window.Size = window.MinimumSize;
                Application.DoEvents();
                Verify(window.ClientRectangle.Contains(window.RectangleToClient(filter.RectangleToScreen(filter.ClientRectangle))) &&
                    window.ClientRectangle.Contains(window.RectangleToClient(screen.RectangleToScreen(screen.ClientRectangle))), "Compact filter and caption fit inside the actual client bounds");
                Verify(screen.ClientSize.Height >= screen.Font.Height && position.ClientSize.Width >= TextRenderer.MeasureText(position.Text, position.Font).Width, "Compact window fits a full caption line and reading position");
                SaveWindow(window, Path.Combine(output, "vr-compact.png"));
                state.Clear("");
                window.ClientSize = new Size(900, 700);
                string steps = String.Join("\r\n", Enumerable.Range(1, 9).Select(n => n.ToString()).ToArray());
                state.Present("screen", steps, VrCaptionWindow.Clock.ElapsedMilliseconds);
                window.RefreshCaptions();
                Application.DoEvents();
                Verify(position.Text.Length == 0, "A fitting caption has no reading-position label");
                window.Size = window.MinimumSize;
                Application.DoEvents();
                Verify(position.Text.Length > 0, "Resizing a persistent caption recalculates overflow without another translation");
                var wait = System.Diagnostics.Stopwatch.StartNew();
                while (FirstLine(screen) == 0 && wait.ElapsedMilliseconds < 6500)
                {
                    Application.DoEvents();
                    System.Threading.Thread.Sleep(25);
                }
                Verify(FirstLine(screen) > 0, "The real window timer advances a persistent caption without new input");
                window.Close();
            }
        }

        static void CheckPlacement()
        {
            Rectangle display = new Rectangle(-22500, -18500, 960, 560);
            using (var overlay = new CaptionOverlay(delegate(Rectangle r) { return display; }))
            {
                IntPtr foreground = GetForegroundWindow();
                overlay.PresentSpeech("On the other side.", display);
                Rectangle preferred = overlay.Bounds;
                Rectangle blocked = new Rectangle(display.Left, display.Top + display.Height / 3, display.Width, display.Height * 2 / 3 + 1);
                Verify(display.Contains(preferred) && blocked.IntersectsWith(preferred), "Speech uses the lower default anchor on a synthetic negative-coordinate monitor");
                overlay.SourceBounds = delegate { return new[] { blocked }; };
                overlay.RepositionSpeech();
                Verify(display.Contains(overlay.Bounds) && !blocked.IntersectsWith(overlay.Bounds), "Speech finds the free upper band when watched text occupies the lower monitor");
                overlay.SourceBounds = delegate { return new[] { display }; };
                overlay.RepositionSpeech();
                Verify(overlay.Bounds == preferred, "A fully obstructed screen picks the nearest equally clear position");
                overlay.SourceBounds = delegate { return new Rectangle[0]; };
                overlay.RepositionSpeech();
                Verify(overlay.Bounds == preferred && GetForegroundWindow() == foreground, "Removing the obstacle restores the default anchor without activation");
            }
            Rectangle[] monitors = { display, new Rectangle(display.Right, display.Top - 90, 1280, 720) };
            Func<Rectangle, Rectangle> visible = r => ScreenCaptionLayer.VisibleSource(r, monitors);
            Rectangle source = new Rectangle(display.Right - 75, display.Top + 55, 175, 42);
            using (var text = new CaptionOverlay(visible, true))
            {
                text.PresentSource("Change platforms", source, null, Color.DarkSlateBlue);
                Verify(text.Showing && text.Bounds == source, "A source straddling two synthetic monitors retains its physical pixel coordinates");
                var layout = typeof(CaptionOverlay).GetMethod("LayoutSource", BindingFlags.Instance | BindingFlags.NonPublic);
                foreach (int dpi in new int[] { 96, 144, 192 })
                {
                    layout.Invoke(text, new object[] { visible(source), dpi });
                    Verify(text.Bounds == source, "Caption reflow at " + dpi + " DPI keeps the source rectangle exact");
                }
                Rectangle clipped = new Rectangle(display.Left - 25, display.Top + 35, 160, 42);
                text.PresentSource("Go to the station", clipped, null, Color.DarkSlateBlue);
                Verify(text.Bounds == Rectangle.Intersect(clipped, display), "A partially off-monitor source is clipped to the visible physical rectangle");
                text.PresentSource("Go to the station", new Rectangle(display.Left - 500, display.Top, 160, 42), null, Color.DarkSlateBlue);
                Verify(!text.Showing, "Moving a source fully beyond both displays clears its old window");
            }
        }

        [STAThread] static int Main(string[] args)
        {
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                CheckPlacement();
                CheckVr(args[0]);
                Console.WriteLine(checks + " targeted checks passed.");
                return 0;
            }
            catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        }
    }
}
