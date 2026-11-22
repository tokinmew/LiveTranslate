using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class ScreenCaptionLayer : IDisposable
    {
        private sealed class Entry
        {
            internal readonly string Text;
            internal readonly Rectangle Source;
            internal readonly string Cover;
            internal readonly Color Panel;
            internal Entry(string text, Rectangle source, string cover, Color panel)
            { Text = text; Source = source; Cover = cover; Panel = panel; }
        }

        private readonly Func<Rectangle, Rectangle> getWorkArea;
        private readonly List<CaptionOverlay> windows = new List<CaptionOverlay>();
        private readonly List<Entry> current = new List<Entry>();
        private readonly Timer oneShot = new Timer { Interval = 12000 };
        private Rectangle[] lastLayout = new Rectangle[0];
        private bool enabled = true;
        private bool capturePaused;
        internal event Action LayoutChanged;

        internal ScreenCaptionLayer() : this(delegate(Rectangle source) {
            return VisibleSource(source, Array.ConvertAll(Screen.AllScreens, monitor => monitor.Bounds));
        }) { }
        internal ScreenCaptionLayer(Func<Rectangle, Rectangle> workArea)
        {
            if (workArea == null) throw new ArgumentNullException("workArea");
            getWorkArea = workArea;
            oneShot.Tick += delegate { Clear(); };
        }

        internal Rectangle[] VisibleBounds
        {
            get
            {
                var visible = new List<Rectangle>();
                foreach (CaptionOverlay window in windows)
                    if (window.Showing) visible.Add(window.Bounds);
                return visible.ToArray();
            }
        }

        internal void Present(IEnumerable regions, string fallback, Rectangle capture, bool temporary, bool show)
        {
            oneShot.Stop();
            current.Clear();
            foreach (object item in regions)
            {
                var row = item as Dictionary<string, object>;
                object value;
                if (row == null || !row.TryGetValue("text", out value) || !(value is string)) continue;
                string text = ((string)value).Trim();
                int left, top, width, height;
                if (text.Length == 0 || !Number(row, "left", out left) || !Number(row, "top", out top)
                    || !Number(row, "width", out width) || !Number(row, "height", out height)
                    || width <= 0 || height <= 0 || width > 32768 || height > 32768
                    || Math.Abs((long)left) > 150000 || Math.Abs((long)top) > 150000) continue;
                object cover;
                row.TryGetValue("cover_png", out cover);
                int rgb;
                Color panel = Number(row, "background_rgb", out rgb) && rgb >= 0 && rgb <= 0xffffff
                    ? Color.FromArgb(255, (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255) : Color.Empty;
                current.Add(new Entry(text, new Rectangle(left, top, width, height), cover as string, panel));
                if (current.Count >= 32) break;
            }
            if (show && current.Count > 0 && windows.Count > 0) BindExistingWindows();
            SetEnabled(show);
            if (temporary && current.Count > 0) oneShot.Start();
        }

        private CaptionOverlay NewWindow()
        {
            var window = new CaptionOverlay(getWorkArea, true);
            window.SetCapturePaused(capturePaused);
            return window;
        }

        private void BindExistingWindows()
        {
            // New/removed neighbors can change OCR enumeration order. Keep a paged caption's
            // native window with its source, reserving every exact match before reusing spares.
            var spare = new List<CaptionOverlay>(windows);
            var ordered = new CaptionOverlay[current.Count];
            for (int i = 0; i < current.Count; i++)
            {
                Entry row = current[i];
                int at = spare.FindIndex(w => w.CaptionText.Length > 0 && w.SourceTarget == row.Source);
                if (at >= 0) { ordered[i] = spare[at]; spare.RemoveAt(at); }
            }
            for (int i = 0; i < current.Count; i++)
            {
                if (ordered[i] != null) continue;
                Entry row = current[i];
                int nearest = -1;
                long distance = Int64.MaxValue;
                for (int j = 0; j < spare.Count; j++)
                {
                    Rectangle old = spare[j].SourceTarget;
                    if (row.Text != spare[j].CaptionText || !row.Source.IntersectsWith(old)) continue;
                    long dx = old.Left - row.Source.Left, dy = old.Top - row.Source.Top;
                    long delta = dx * dx + dy * dy;
                    if (delta < distance) { distance = delta; nearest = j; }
                }
                if (nearest >= 0) { ordered[i] = spare[nearest]; spare.RemoveAt(nearest); }
            }
            for (int i = 0; i < ordered.Length; i++)
            {
                if (ordered[i] != null) continue;
                if (spare.Count == 0) ordered[i] = NewWindow();
                else { ordered[i] = spare[0]; spare.RemoveAt(0); }
            }
            windows.Clear();
            windows.AddRange(ordered);
            windows.AddRange(spare);
        }

        private static bool Number(Dictionary<string, object> row, string key, out int number)
        {
            object value;
            number = 0;
            return row.TryGetValue(key, out value) && Int32.TryParse(Convert.ToString(value), out number);
        }

        internal void SetEnabled(bool value)
        {
            enabled = value;
            int visible = enabled ? current.Count : 0;
            for (int i = 0; i < visible; i++)
            {
                if (i == windows.Count) windows.Add(NewWindow());
                windows[i].PresentSource(current[i].Text, current[i].Source, current[i].Cover, current[i].Panel);
            }
            for (int i = visible; i < windows.Count; i++) windows[i].ClearCaption();
            NotifyLayout();
        }

        private void NotifyLayout()
        {
            if (LayoutChanged == null) return;
            Rectangle[] now = VisibleBounds;
            if (now.Length == lastLayout.Length)
            {
                int i = 0;
                while (i < now.Length && now[i] == lastLayout[i]) i++;
                if (i == now.Length) return;
            }
            lastLayout = now;
            LayoutChanged();
        }

        internal void Clear()
        {
            oneShot.Stop();
            current.Clear();
            SetEnabled(enabled);
        }

        internal bool BeginCapturePause()
        {
            capturePaused = true;
            bool hidden = false;
            foreach (CaptionOverlay window in windows) hidden |= window.SetCapturePaused(true);
            return hidden;
        }

        internal void EndCapturePause()
        {
            capturePaused = false;
            bool restored = false;
            foreach (CaptionOverlay window in windows) restored |= window.SetCapturePaused(false);
            // Speech may have arrived while the source windows were hidden for capture.
            if (restored && LayoutChanged != null)
            {
                lastLayout = VisibleBounds;
                LayoutChanged();
            }
        }

        internal static Rectangle VisibleSource(Rectangle source, IEnumerable<Rectangle> displays)
        {
            // A user-selected area may span displays. Preserve the physical source
            // coordinates of every visible part, including both sides of a seam.
            Rectangle result = Rectangle.Empty;
            foreach (Rectangle display in displays)
            {
                Rectangle part = Rectangle.Intersect(source, display);
                if (part.Width > 0 && part.Height > 0)
                    result = result.IsEmpty ? part : Rectangle.Union(result, part);
            }
            return result;
        }

        public void Dispose()
        {
            oneShot.Dispose();
            foreach (CaptionOverlay window in windows) window.Dispose();
            windows.Clear();
            current.Clear();
        }
    }
}
