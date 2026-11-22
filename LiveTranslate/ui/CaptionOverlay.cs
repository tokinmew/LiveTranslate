using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace LiveTranslate
{
    // Unowned so minimizing the dashboard on another monitor leaves the captions visible.
    internal sealed class CaptionOverlay : Form
    {
        private const int LinesPerPage = 3;
        private const int MaxNativeMeasureLength = 4096;
        private const int WsExLayered = 0x00080000, WsExTransparent = 0x00000020;
        private const int WsExNoActivate = 0x08000000, WsExToolWindow = 0x00000080;
        private const uint ExcludeFromCapture = 0x11;
        private const TextFormatFlags TextFlags = TextFormatFlags.NoPrefix | TextFormatFlags.NoPadding
            | TextFormatFlags.SingleLine;

        [DllImport("user32.dll")] private static extern bool SetWindowDisplayAffinity(IntPtr hwnd, uint affinity);
        [DllImport("user32.dll")] private static extern bool GetWindowDisplayAffinity(IntPtr hwnd, out uint affinity);
        [DllImport("user32.dll")] private static extern bool SetLayeredWindowAttributes(IntPtr hwnd, uint key, byte alpha, uint flags);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern bool SetProp(IntPtr hwnd, string name, IntPtr value);
        [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hwnd);
        [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr hwnd, IntPtr insertAfter,
            int x, int y, int cx, int cy, uint flags);
        [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] private static extern IntPtr MonitorFromPoint(Point point, uint flags);
        [DllImport("shcore.dll")] private static extern int GetDpiForMonitor(IntPtr monitor, int type, out uint x, out uint y);

        private readonly Timer timer = new Timer();
        private readonly Stopwatch clock = Stopwatch.StartNew();
        private readonly List<string> lines = new List<string>();
        private readonly Func<Rectangle, Rectangle> getWorkArea;
        private readonly bool sourceWindow;
        private bool exclusionWorks, bottomAligned, capturePaused, usePaintFallback;
        private Bitmap cover;
        private string encodedCover;
        private Color panel;
        private Size speechCard;
        internal Func<Rectangle[]> SourceBounds { get; set; }
        private Font face;
        private string caption = "";
        private Rectangle target, workArea, sourceBounds;
        private int dpi, lineHeight, horizontalPadding, verticalPadding, firstLine, maxWindowHeight;
        private long pageEnds, nextDisplayCheck;

        internal CaptionOverlay() : this(WorkArea) { }

        // A supplied display layout also allows the native overlay to be exercised on
        // an off-screen synthetic monitor without putting test windows on a user's screen.
        internal CaptionOverlay(Func<Rectangle, Rectangle> getWorkArea) : this(getWorkArea, false) { }

        internal CaptionOverlay(Func<Rectangle, Rectangle> getWorkArea, bool sourceWindow)
        {
            if (getWorkArea == null) throw new ArgumentNullException("getWorkArea");
            this.getWorkArea = getWorkArea;
            this.sourceWindow = sourceWindow;
            Text = sourceWindow ? "Live Translate screen caption" : "Live Translate captions";
            AccessibleName = Text;
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            ShowInTaskbar = false;
            // Native visibility sets HWND_TOPMOST without activation. Setting the
            // WinForms TopMost property can activate a freshly created hidden form.
            AutoScaleMode = AutoScaleMode.None;
            BackColor = SystemInformation.HighContrast ? SystemColors.Window : Color.FromArgb(15, 22, 32);
            ForeColor = SystemInformation.HighContrast ? SystemColors.WindowText : Color.FromArgb(250, 252, 255);
            TabStop = false;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            timer.Interval = 200;
            timer.Tick += OnTimer;
        }

        internal long CaptureWindowId
        {
            get { return IsDisposed || Disposing ? 0 : Handle.ToInt64(); }
        }

        internal bool Showing { get { return IsHandleCreated && IsWindowVisible(Handle); } }
        internal Rectangle SourceTarget { get { return target; } }
        internal string CaptionText { get { return caption; } }

        internal bool SetCapturePaused(bool value)
        {
            capturePaused = value;
            if (!sourceWindow || !IsHandleCreated || exclusionWorks) return false;
            bool wasShowing = Showing;
            if (value && wasShowing) SetCaptionVisible(false);
            else if (!value && !wasShowing && caption.Length != 0 && !sourceBounds.IsEmpty)
            {
                SetCaptionVisible(true);
                timer.Start();
                return true;
            }
            return value && wasShowing;
        }

        private void SetCaptionVisible(bool show)
        {
            // WinForms Form.Show can assign keyboard focus even on a WS_EX_NOACTIVATE
            // top-level form. Specify the native no-activation guarantee on the actual
            // visibility operation and leave the current foreground window untouched.
            const uint keep = 0x0001 | 0x0002 | 0x0010 | 0x0200; // NOSIZE, NOMOVE, NOACTIVATE, NOOWNERZORDER
            const uint showWindow = 0x0040, hideWindow = 0x0080, keepOrder = 0x0004;
            SetWindowPos(Handle, show ? new IntPtr(-1) : IntPtr.Zero, 0, 0, 0, 0,
                keep | (show ? showWindow : hideWindow | keepOrder));
        }

        protected override bool ShowWithoutActivation { get { return true; } }
        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams cp = base.CreateParams;
                cp.ExStyle &= ~0x00040000; // WS_EX_APPWINDOW
                cp.ExStyle |= WsExNoActivate | WsExToolWindow | WsExLayered | WsExTransparent;
                return cp;
            }
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            // Identify source cards for the capture worker, including on systems where
            // the compositor cannot exclude them and capture needs a temporary pause.
            if (sourceWindow) SetProp(Handle, "LiveTranslate.SourceCaption", new IntPtr(1));
            uint applied;
            exclusionWorks = SetWindowDisplayAffinity(Handle, ExcludeFromCapture)
                && GetWindowDisplayAffinity(Handle, out applied) && applied == ExcludeFromCapture;
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == 0x0084) { m.Result = new IntPtr(-1); return; } // HTTRANSPARENT
            if (m.Msg == 0x0021) { m.Result = new IntPtr(3); return; }  // MA_NOACTIVATE
            base.WndProc(ref m);
        }

        private static string Normalize(string text)
        {
            if (String.IsNullOrWhiteSpace(text)) return "";
            StringBuilder result = new StringBuilder(text.Length);
            bool space = false;
            foreach (char c in text)
            {
                if (Char.IsWhiteSpace(c) || Char.IsControl(c))
                    space = result.Length > 0;
                else
                {
                    if (space) result.Append(' ');
                    result.Append(c);
                    space = false;
                }
            }
            return result.ToString();
        }

        private static int Scale(int pixels, int dots)
        {
            return Math.Max(1, (int)Math.Round(pixels * dots / 96.0));
        }

        private static int MonitorDpi(Rectangle area)
        {
            Point center = new Point(area.Left + area.Width / 2, area.Top + area.Height / 2);
            uint x, y;
            // The app's entry point starts in per-monitor V2 awareness on Windows 11.
            int result = GetDpiForMonitor(MonitorFromPoint(center, 2), 0, out x, out y);
            return result == 0 && x >= 48 && x <= 960 ? (int)x : 96;
        }

        internal static Rectangle WorkArea(Rectangle region)
        {
            Screen monitor = region.Width > 0 && region.Height > 0
                ? Screen.FromRectangle(region) : Screen.FromHandle(GetForegroundWindow());
            return monitor.WorkingArea;
        }

        internal static Rectangle Place(Rectangle area, Rectangle region, Size card, int dots)
        {
            int width = Math.Min(Math.Max(1, card.Width), Math.Max(1, area.Width));
            int height = Math.Min(Math.Max(1, card.Height), Math.Max(1, area.Height));
            int margin = Math.Min(Math.Max(Scale(15, dots), area.Height / 24), Math.Max(0, (area.Height - height) / 2));
            int x = area.Left + (area.Width - width) / 2;
            Rectangle upper = new Rectangle(x, area.Top + margin, width, height);
            Rectangle lower = new Rectangle(x, area.Bottom - margin - height, width, height);
            // A full-screen scan places English above the usual source subtitle area.
            // For a small crop use the side with less overlap.
            if (region.Contains(area)) return upper;
            Rectangle topOverlap = Rectangle.Intersect(upper, region), bottomOverlap = Rectangle.Intersect(lower, region);
            long upperPixels = (long)topOverlap.Width * topOverlap.Height;
            long lowerPixels = (long)bottomOverlap.Width * bottomOverlap.Height;
            return lowerPixels > upperPixels ? upper : lower;
        }

        private Rectangle PlaceSpeech()
        {
            Rectangle preferred = Place(workArea, Rectangle.Empty, speechCard, dpi);
            Rectangle[] sources = SourceBounds == null ? null : SourceBounds();
            if (sources == null || !Array.Exists(sources, preferred.IntersectsWith)) return preferred;
            int gap = Scale(6, dpi);
            var xs = new List<int> {preferred.Left};
            var ys = new List<int> {preferred.Top};
            foreach (Rectangle source in sources)
            {
                if (!workArea.IntersectsWith(source)) continue;
                xs.Add(Math.Max(workArea.Left, Math.Min(workArea.Right - preferred.Width, source.Left - preferred.Width - gap)));
                xs.Add(Math.Max(workArea.Left, Math.Min(workArea.Right - preferred.Width, source.Right + gap)));
                ys.Add(Math.Max(workArea.Top, Math.Min(workArea.Bottom - preferred.Height, source.Top - preferred.Height - gap)));
                ys.Add(Math.Max(workArea.Top, Math.Min(workArea.Bottom - preferred.Height, source.Bottom + gap)));
            }
            Rectangle best = preferred;
            long leastOverlap = Int64.MaxValue, leastMotion = Int64.MaxValue;
            foreach (int x in xs) foreach (int y in ys)
            {
                Rectangle candidate = new Rectangle(x,y,preferred.Width,preferred.Height);
                long overlap = 0;
                foreach (Rectangle source in sources)
                {
                    Rectangle intersect = Rectangle.Intersect(candidate,source);
                    overlap += (long)intersect.Width * intersect.Height;
                }
                long dx = x-preferred.Left, dy = y-preferred.Top;
                long motion = dx*dx + dy*dy;
                if (overlap < leastOverlap || (overlap == leastOverlap && motion < leastMotion))
                { best = candidate; leastOverlap = overlap; leastMotion = motion; }
            }
            return best;
        }

        internal void RepositionSpeech()
        {
            if (!bottomAligned || !Showing) return;
            Rectangle position = PlaceSpeech();
            if (position != Bounds) MoveWindowWithoutFocus(position);
        }

        private void MoveWindowWithoutFocus(Rectangle bounds)
        {
            SetWindowPos(Handle, IntPtr.Zero, bounds.X, bounds.Y, bounds.Width, bounds.Height,
                0x0004 | 0x0010 | 0x0200); // NOZORDER, NOACTIVATE, NOOWNERZORDER
        }

        private int Measure(string value)
        {
            // GDI can return zero for an oversized string. Treat it as wider
            // than the display and measure bounded prefixes during word wrapping.
            if (value.Length > MaxNativeMeasureLength) return 65535;
            return TextRenderer.MeasureText(value, face, new Size(Int32.MaxValue, Int32.MaxValue), TextFlags).Width;
        }

        // A URL, OCR token, or name may be wider than an entire line. Split at a text-element
        // boundary to keep surrogate pairs and combining marks together.
        private string SplitLongWord(string word, int available)
        {
            int[] starts = StringInfo.ParseCombiningCharacters(word);
            int from = 0;
            while (from < starts.Length)
            {
                int lo = from + 1, hi = Math.Min(starts.Length, from + MaxNativeMeasureLength);
                while (lo < hi)
                {
                    int count = lo + (hi - lo + 1) / 2;
                    int end = count == starts.Length ? word.Length : starts[count];
                    if (Measure(word.Substring(starts[from], end - starts[from])) <= available) lo = count;
                    else hi = count - 1;
                }
                int limit = lo == starts.Length ? word.Length : starts[lo];
                string piece = word.Substring(starts[from], limit - starts[from]);
                if (lo == starts.Length) return piece;
                lines.Add(piece);
                from = lo;
            }
            return "";
        }

        private void Wrap(int available)
        {
            lines.Clear();
            string line = "";
            foreach (string word in caption.Split(' '))
            {
                string candidate = line.Length == 0 ? word : line + " " + word;
                if (Measure(candidate) <= available) { line = candidate; continue; }
                if (line.Length != 0) lines.Add(line);
                line = Measure(word) <= available ? word : SplitLongWord(word, available);
            }
            if (line.Length != 0) lines.Add(line);
        }

        private void LayoutCaption(Rectangle area, int newDpi)
        {
            if (sourceWindow)
            {
                LayoutSource(area, newDpi);
                return;
            }
            if (face == null || newDpi != dpi)
            {
                if (face != null) face.Dispose();
                dpi = newDpi;
                face = new Font("Segoe UI Semibold", Scale(24, dpi), FontStyle.Regular, GraphicsUnit.Pixel);
            }
            workArea = area;
            horizontalPadding = Math.Min(Scale(24, dpi), Math.Max(1, area.Width / 12));
            verticalPadding = Scale(10, dpi);
            lineHeight = Math.Max(1, TextRenderer.MeasureText("Ag", face,
                new Size(Int32.MaxValue, Int32.MaxValue), TextFlags).Height + Scale(2, dpi));
            int maxWidth = Math.Min(Scale(960, dpi), Math.Max(1, area.Width - Math.Max(Scale(24, dpi), area.Width / 8)));
            // Windows may impose the primary monitor's maximum tracking size on
            // a window being positioned on another display. Wrap to the same bound.
            Size nativeLimit = SystemInformation.MaxWindowTrackSize;
            if (nativeLimit.Width > 0) maxWidth = Math.Min(maxWidth, nativeLimit.Width);
            maxWindowHeight = nativeLimit.Height > 0 ? Math.Min(area.Height, nativeLimit.Height) : area.Height;
            Wrap(Math.Max(1, maxWidth - horizontalPadding * 2));
            firstLine = 0;
            DisplayPage();
        }

        private void SizeSourceText(int pixels, int available)
        {
            if (face == null || face.Size != pixels)
            {
                if (face != null) face.Dispose();
                face = new Font("Segoe UI Semibold", pixels, FontStyle.Regular, GraphicsUnit.Pixel);
            }
            lineHeight = Math.Max(1, TextRenderer.MeasureText("Ag", face,
                new Size(Int32.MaxValue, Int32.MaxValue), TextFlags).Height);
            Wrap(available);
        }

        private void LayoutSource(Rectangle display, int dots)
        {
            // Locate the current page by its text offset, since moving or resizing a detected
            // word can change wrapping. Repeated geometry updates must not restart the dwell.
            int offset = 0;
            for (int i = 0; i < firstLine && i < lines.Count; i++)
                offset += lines[i].Replace(" ", "").Length;
            long priorDeadline = pageEnds;
            dpi = dots;
            workArea = display;
            sourceBounds = Rectangle.Intersect(target, display);
            if (sourceBounds.Width < 1 || sourceBounds.Height < 1) { ClearCaption(); return; }
            horizontalPadding = Math.Min(Scale(2, dpi), sourceBounds.Width / 24);
            verticalPadding = Math.Min(Scale(1, dpi), sourceBounds.Height / 30);
            int width = Math.Max(1, sourceBounds.Width - 2 * horizontalPadding);
            int height = Math.Max(1, sourceBounds.Height - 2 * verticalPadding);
            maxWindowHeight = sourceBounds.Height;
            // Large labels can fit their entire English translation. In a tight
            // subtitle box preserve a readable size and page within the same pixels.
            int high = Math.Min(Scale(44, dpi), height);
            int low = Math.Min(high, Math.Min(Scale(9, dpi), Math.Max(1, (int)(height * .70))));
            // A short word such as "Station" can often fit a single ideograph's
            // box intact by going one or two pixels smaller.
            bool wholeWord = false;
            if (caption.Length <= 32 && caption.IndexOf(' ') < 0 && 2L * width >= height)
            {
                int compact = Math.Min(low, Scale(6, dpi));
                SizeSourceText(compact, width);
                wholeWord = lines.Count == 1 && Measure(caption) <= width && lineHeight <= height;
                if (wholeWord) low = compact;
            }
            int best = low;
            while (low <= high)
            {
                int mid = low + (high - low) / 2;
                SizeSourceText(mid, width);
                bool fits = (long)lineHeight * lines.Count <= height && (!wholeWord || lines.Count == 1);
                if (fits) foreach (string line in lines) if (Measure(line) > width) { fits = false; break; }
                if (fits) { best = mid; low = mid + 1; }
                else high = mid - 1;
            }
            SizeSourceText(best, width);
            firstLine = 0;
            while (firstLine + 1 < lines.Count)
            {
                int length = lines[firstLine].Replace(" ", "").Length;
                if (offset < length) break;
                offset -= length;
                firstLine++;
            }
            DisplayPage();
            if (priorDeadline > 0) pageEnds = priorDeadline;
        }

        private int PageLines
        {
            get
            {
                int fit = Math.Max(1, (maxWindowHeight - 2 * verticalPadding) / Math.Max(1, lineHeight));
                return Math.Min(sourceWindow ? fit : Math.Min(LinesPerPage, fit), Math.Max(0, lines.Count - firstLine));
            }
        }

        private void DisplayPage()
        {
            int width = 0;
            int count = PageLines;
            for (int i = 0; i < count; i++)
            {
                string line = lines[firstLine + i];
                width = Math.Max(width, Measure(line));
            }
            Size card = new Size(width + horizontalPadding * 2, lineHeight * count + verticalPadding * 2);
            if (bottomAligned) speechCard = card;
            Rectangle bounds = sourceWindow ? sourceBounds
                : bottomAligned ? PlaceSpeech() : Place(workArea, target, card, dpi);
            DrawPage(bounds);
            RenewPageTime();
            nextDisplayCheck = clock.ElapsedMilliseconds + 1000;
        }

        private void RenewPageTime()
        {
            int characters = 0;
            for (int i = firstLine; i < firstLine + PageLines; i++) characters += lines[i].Length;
            pageEnds = clock.ElapsedMilliseconds + Math.Max(4500, Math.Min(15000, characters * 62 + 1200));
        }

        private void DrawPage(Rectangle bounds)
        {
            if (!usePaintFallback && CaptionSurface.Render(Handle, bounds, sourceWindow, face, lines, firstLine,
                    PageLines, lineHeight, horizontalPadding, verticalPadding, dpi, cover, target, panel))
            {
                // UpdateLayeredWindow can move the HWND without refreshing WinForms'
                // cached bounds. Speech placement needs the current physical rectangles.
                UpdateBounds();
                return;
            }
            // Drivers without per-pixel composition can still key out the space around spoken
            // captions. Source text needs a fully opaque matched fill to hide its old letters.
            usePaintFallback = true;
            bool keyed = !sourceWindow && !SystemInformation.HighContrast;
            SetLayeredWindowAttributes(Handle, (uint)ColorTranslator.ToWin32(CaptionSurface.SpeechTransparencyKey),
                255, keyed ? 1U : 2U);
            MoveWindowWithoutFocus(bounds);
            Invalidate();
        }

        internal void Present(string text, Rectangle captureBounds)
        {
            if (IsDisposed || Disposing) return;
            string normalized = Normalize(text);
            if (normalized.Length == 0) { ClearCaption(); return; }
            Rectangle area = getWorkArea(captureBounds);
            int newDpi = MonitorDpi(area);
            if (Showing && caption == normalized && target == captureBounds && area == workArea && newDpi == dpi)
                return;
            caption = normalized;
            target = captureBounds;
            LayoutCaption(area, newDpi);
            if (!Showing) SetCaptionVisible(true);
            if (Showing) timer.Start();
        }

        internal void PresentSpeech(string text, Rectangle captureBounds)
        {
            bottomAligned = true;
            bool repeated = Showing && caption == Normalize(text) && target == captureBounds;
            Present(text, captureBounds);
            if (repeated && Showing && firstLine + PageLines == lines.Count) RenewPageTime();
        }

        internal void PresentSource(string text, Rectangle location, string encoded, Color background = default(Color))
        {
            if (IsDisposed || Disposing) return;
            string normalized = Normalize(text);
            if (normalized.Length == 0) { ClearCaption(); return; }
            Rectangle area = getWorkArea(location);
            int newDpi = MonitorDpi(area);
            bool newMask = target.Size != location.Size || encodedCover != encoded;
            bool appearanceChanged = newMask || panel != background;
            panel = background;
            if (newMask)
            {
                if (cover != null) cover.Dispose();
                cover = CaptionSurface.DecodeCover(encoded, location.Size);
                encodedCover = encoded;
            }
            bool newText = caption != normalized;
            Rectangle visible = Rectangle.Intersect(location, area);
            if (newText || visible.Size != sourceBounds.Size || dpi != newDpi)
            {
                if (newText) { firstLine = 0; pageEnds = 0; }
                caption = normalized;
                target = location;
                LayoutCaption(area, newDpi);
            }
            else if (appearanceChanged || target != location || area != workArea)
            {
                target = location;
                workArea = area;
                sourceBounds = visible;
                if (!sourceBounds.IsEmpty) DrawPage(sourceBounds);
            }
            if (caption.Length == 0) return;
            if ((!capturePaused || exclusionWorks) && !Showing) SetCaptionVisible(true);
            if (Showing) timer.Start();
        }

        internal void ClearCaption()
        {
            if (IsDisposed || Disposing) return;
            timer.Stop();
            if (Showing) SetCaptionVisible(false);
            caption = "";
            sourceBounds = Rectangle.Empty;
            if (cover != null) { cover.Dispose(); cover = null; }
            encodedCover = null;
            panel = Color.Empty;
            lines.Clear();
            firstLine = 0;
            pageEnds = 0;
        }

        private void OnTimer(object sender, EventArgs args)
        {
            long now = clock.ElapsedMilliseconds;
            if (now >= nextDisplayCheck)
            {
                nextDisplayCheck = now + 1000;
                Rectangle area = getWorkArea(target);
                int newDpi = MonitorDpi(area);
                if (area != workArea || newDpi != dpi)
                {
                    LayoutCaption(area, newDpi);
                    return;
                }
            }
            if (now < pageEnds) return;
            if (firstLine + PageLines < lines.Count)
            {
                firstLine += PageLines;
                DisplayPage();
            }
            else if (sourceWindow)
            {
                if (lines.Count > PageLines && firstLine > 0) { firstLine = 0; DisplayPage(); }
            }
            else ClearCaption();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            if (!usePaintFallback) return;
            base.OnPaint(e);
            CaptionSurface.Paint(e.Graphics, ClientSize, sourceWindow, face, lines, firstLine,
                PageLines, lineHeight, horizontalPadding, verticalPadding, dpi, SystemInformation.HighContrast,
                null, Point.Empty, panel, true);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                timer.Dispose();
                if (cover != null) { cover.Dispose(); cover = null; }
                if (face != null) { face.Dispose(); face = null; }
            }
            base.Dispose(disposing);
        }
    }
}
