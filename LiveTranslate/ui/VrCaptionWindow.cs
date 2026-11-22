using System;
using System.Diagnostics;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class VrCaptionState
    {
        internal static readonly string[] Channels = { "audio", "screen", "text" };
        readonly string[] captions = new string[3];
        readonly long[] expiry = new long[3];

        internal void Present(string kind, string text, long now)
        {
            int index = kind == "screen_once" ? 1 : Array.IndexOf(Channels, kind);
            if (index < 0 || String.IsNullOrWhiteSpace(text)) return;
            captions[index] = text.Trim();
            // Screen captions follow the screen watcher. Speech and pasted text need reading time.
            expiry[index] = kind == "screen" ? Int64.MaxValue : now + Math.Max(6000L, Math.Min(120000L, 1700L + 85L * captions[index].Length));
        }

        internal void Clear(string kind)
        {
            for (int i = 0; i < Channels.Length; i++)
                if (String.IsNullOrEmpty(kind) || String.Equals(Channels[i], kind, StringComparison.Ordinal))
                {
                    captions[i] = null;
                    expiry[i] = 0;
                }
        }

        internal string Read(int index, long now)
        {
            if (expiry[index] <= now) captions[index] = null;
            return captions[index];
        }

        internal int NextUpdate(long now)
        {
            long next = Int64.MaxValue;
            for (int i = 0; i < Channels.Length; i++)
                if (captions[i] != null && expiry[i] > now && expiry[i] < next) next = expiry[i];
            return next == Int64.MaxValue ? 0 : (int)Math.Min(Int32.MaxValue, next - now);
        }
    }

    // An ordinary, opaque top-level HWND is selectable by PC VR desktop/window capture.
    // Never apply the desktop caption layer's display affinity or click-through style here.
    internal sealed class VrCaptionWindow : Form
    {
        internal const string WindowTitle = "LiveTranslate VR captions";
        internal const string CaptureMarker = "LiveTranslate.VrCaption";
        internal static readonly Stopwatch Clock = Stopwatch.StartNew();
        static readonly Color Background = Color.FromArgb(15, 20, 30);
        static readonly Color Card = Color.FromArgb(29, 37, 51);
        static readonly Color Ink = Color.FromArgb(250, 251, 255);
        static readonly Color Muted = Color.FromArgb(190, 201, 220);
        static readonly Color[] SourceColors = { Color.FromArgb(133, 237, 209), Color.FromArgb(192, 181, 255), Color.FromArgb(154, 210, 253) };
        static readonly string[] SourceNames = { "Speech", "Screen", "Typed text" };

        [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "SetPropW", ExactSpelling = true)]
        static extern bool SetProp(IntPtr window, string name, IntPtr value);
        [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "RemovePropW", ExactSpelling = true)]
        static extern IntPtr RemoveProp(IntPtr window, string name);
        [DllImport("user32.dll", EntryPoint = "SendMessageW")]
        static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
        const int GetLineCount = 0x00BA, GetFirstVisibleLine = 0x00CE, ScrollLines = 0x00B6;

        readonly VrCaptionState state;
        readonly TableLayoutPanel rows = new TableLayoutPanel();
        readonly Panel[] cards = new Panel[3];
        readonly RichTextBox[] bodies = new RichTextBox[3];
        readonly Label[] ranges = new Label[3];
        readonly long[] nextPage = new long[3];
        readonly bool[] manualReading = new bool[3];
        readonly string[] displayed = new string[3];
        readonly Label idle = new Label();
        readonly ComboBox filter = new ComboBox();
        readonly Timer expiryTimer = new Timer();
        Font captionFont;
        readonly Font headingFont = new Font("Segoe UI", 11F, FontStyle.Bold);
        readonly Font rangeFont = new Font("Segoe UI", 9F);
        readonly Font idleFont = new Font("Segoe UI", 15F);
        readonly Font toolbarFont = new Font("Segoe UI", 10F);
        int visibleSources = -1;
        int lastSourceMask = -1;
        bool reflowPending;

        internal VrCaptionWindow(VrCaptionState value)
        {
            state = value;
            Text = WindowTitle;
            AccessibleName = WindowTitle;
            BackColor = Background;
            Font = toolbarFont;
            MinimumSize = new Size(430, 335);
            ClientSize = new Size(800, 380);
            AutoScaleDimensions = new SizeF(96F, 96F);
            AutoScaleMode = AutoScaleMode.Dpi;
            ShowInTaskbar = true;
            StartPosition = FormStartPosition.Manual;

            var toolbar = new TableLayoutPanel { Dock = DockStyle.Top, Height = 52, Padding = new Padding(15, 8, 15, 8), ColumnCount = 2, RowCount = 1, BackColor = Background };
            toolbar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            toolbar.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            toolbar.Controls.Add(new Label { Text = "Live captions", Font = headingFont, ForeColor = Ink, AutoSize = true, Anchor = AnchorStyles.Left }, 0, 0);
            filter.AccessibleName = "Caption source";
            filter.DropDownStyle = ComboBoxStyle.DropDownList;
            filter.Width = 155;
            filter.Anchor = AnchorStyles.Right;
            filter.Items.Add("All sources");
            filter.Items.AddRange(SourceNames);
            filter.SelectedIndex = 0;
            toolbar.Controls.Add(filter, 1, 0);

            rows.Dock = DockStyle.Fill;
            rows.Padding = new Padding(12, 5, 12, 6);
            rows.ColumnCount = 1;
            rows.RowCount = 3;
            rows.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            for (int i = 0; i < cards.Length; i++)
            {
                rows.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));
                Panel card = new Panel { Dock = DockStyle.Fill, Margin = new Padding(3), Padding = new Padding(0, 3, 12, 4), BackColor = Card };
                var contentPanel = new Panel { Dock = DockStyle.Fill, Padding = new Padding(12, 0, 0, 0) };
                var header = new Panel { Dock = DockStyle.Top, Height = 26 };
                var title = new Label { Dock = DockStyle.Left, AutoSize = true, Text = SourceNames[i], ForeColor = SourceColors[i], Font = headingFont };
                var range = new Label { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleRight, ForeColor = Muted, Font = rangeFont, AccessibleName = SourceNames[i] + " reading position" };
                header.Controls.Add(range);
                header.Controls.Add(title);
                ranges[i] = range;
                var viewport = new Panel { Dock = DockStyle.Fill };
                RichTextBox body = new RichTextBox { Dock = DockStyle.Top, ReadOnly = true, BorderStyle = BorderStyle.None, BackColor = Card, ForeColor = Ink, DetectUrls = false, WordWrap = true, ScrollBars = RichTextBoxScrollBars.Vertical, AccessibleName = SourceNames[i] + " translation" };
                int channel = i;
                body.MouseDown += delegate { manualReading[channel] = true; };
                body.MouseWheel += delegate { manualReading[channel] = true; };
                body.KeyDown += delegate { manualReading[channel] = true; };
                body.VScroll += delegate
                {
                    if (Control.MouseButtons == MouseButtons.Left) manualReading[channel] = true;
                    if (manualReading[channel]) UpdatePage(channel, Clock.ElapsedMilliseconds);
                };
                viewport.SizeChanged += delegate
                {
                    if (reflowPending || !IsHandleCreated || Disposing || IsDisposed) return;
                    reflowPending = true;
                    BeginInvoke((MethodInvoker)delegate
                    {
                        reflowPending = false;
                        if (!Disposing && !IsDisposed) RefreshCaptions();
                    });
                };
                var rail = new Panel { Dock = DockStyle.Left, Width = 3, BackColor = SourceColors[i] };
                viewport.Controls.Add(body);
                contentPanel.Controls.Add(viewport);
                contentPanel.Controls.Add(header);
                card.Controls.Add(contentPanel);
                card.Controls.Add(rail);
                cards[i] = card;
                bodies[i] = body;
                rows.Controls.Add(card, 0, i);
            }

            idle.Dock = DockStyle.Fill;
            idle.TextAlign = ContentAlignment.MiddleCenter;
            idle.Padding = new Padding(18);
            idle.ForeColor = Muted;
            idle.Font = idleFont;
            var content = new Panel { Dock = DockStyle.Fill };
            content.Controls.Add(rows);
            content.Controls.Add(idle);
            Controls.Add(content);
            Controls.Add(toolbar);

            expiryTimer.Tick += delegate { RefreshCaptions(); };
            filter.SelectedIndexChanged += delegate { RefreshCaptions(); };
            ResizeEnd += delegate { ResizeType(); };
            content.SizeChanged += delegate { ResizeType(); };
            Shown += delegate { RefreshCaptions(); };
            RefreshCaptions();
        }

        // Showing a new caption or expiring an old one never changes foreground focus.
        protected override bool ShowWithoutActivation { get { return true; } }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            SetProp(Handle, CaptureMarker, new IntPtr(1));
        }

        protected override void DestroyHandle()
        {
            if (IsHandleCreated) RemoveProp(Handle, CaptureMarker);
            base.DestroyHandle();
        }

        internal void RefreshCaptions()
        {
            expiryTimer.Stop();
            long now = Clock.ElapsedMilliseconds;
            int mask = 0;
            int count = 0;
            for (int i = 0; i < bodies.Length; i++)
            {
                string text = state.Read(i, now) ?? "";
                if (text != displayed[i])
                {
                    displayed[i] = text;
                    manualReading[i] = false;
                    nextPage[i] = 0;
                    bodies[i].Text = text;
                    bodies[i].Select(0, 0);
                    bodies[i].ScrollToCaret();
                }
                if (text.Length != 0 && (filter.SelectedIndex == 0 || filter.SelectedIndex == i + 1))
                {
                    mask |= 1 << i;
                    count++;
                }
            }
            if (mask != lastSourceMask)
            {
                lastSourceMask = mask;
                rows.SuspendLayout();
                for (int i = 0; i < cards.Length; i++)
                {
                    bool show = (mask & (1 << i)) != 0;
                    rows.RowStyles[i].SizeType = show ? SizeType.Percent : SizeType.Absolute;
                    rows.RowStyles[i].Height = show ? 100F / count : 0;
                    cards[i].Visible = show;
                }
                rows.Visible = count > 0;
                idle.Visible = count == 0;
                rows.ResumeLayout(true);
                visibleSources = count;
                ResizeType();
            }
            int delay = state.NextUpdate(now);
            if (count == 0)
            {
                string waiting = filter.SelectedIndex == 0 ? "Waiting for a translation" :
                    "Waiting for " + SourceNames[filter.SelectedIndex - 1].ToLowerInvariant() + " captions";
                idle.Text = waiting + "\r\nSelect this window in your headset's PC desktop view.";
            }
            for (int i = 0; i < bodies.Length; i++)
            {
                if ((mask & (1 << i)) == 0) { nextPage[i] = 0; continue; }
                int due = UpdatePage(i, now);
                if (due > 0 && (delay == 0 || due < delay)) delay = due;
            }
            if (delay > 0) { expiryTimer.Interval = Math.Max(20, delay); expiryTimer.Start(); }
        }

        // Read the native word-wrapped lines so paging follows the actual window size
        // and font. Leave the complete text in the control for selection and copying.
        int UpdatePage(int index, long now)
        {
            RichTextBox body = bodies[index];
            int available = body.Parent.ClientSize.Height;
            if (!body.IsHandleCreated || !body.Visible || available <= 0) return 0;
            int total = SendMessage(body.Handle, GetLineCount, IntPtr.Zero, IntPtr.Zero).ToInt32();
            int secondStart = total > 1 ? body.GetFirstCharIndexFromLine(1) : -1;
            int height = secondStart >= 0 ? body.GetPositionFromCharIndex(secondStart).Y - body.GetPositionFromCharIndex(0).Y : 0;
            if (height < 1) height = body.Font.Height;
            int visible = Math.Max(1, (available - 2) / height);
            // Stop on a whole line. Rich Edit otherwise draws a sliver of the next
            // line across the bottom of a small pinned window.
            int bodyHeight = Math.Min(available, visible * height + 2);
            if (body.Height != bodyHeight)
            {
                body.Height = bodyHeight;
                total = SendMessage(body.Handle, GetLineCount, IntPtr.Zero, IntPtr.Zero).ToInt32();
            }
            int first = SendMessage(body.Handle, GetFirstVisibleLine, IntPtr.Zero, IntPtr.Zero).ToInt32();
            if (total <= visible) { ranges[index].Text = ""; nextPage[index] = 0; return 0; }
            if (!manualReading[index] && nextPage[index] > 0 && now >= nextPage[index] && first + visible < total)
            {
                SendMessage(body.Handle, ScrollLines, IntPtr.Zero, new IntPtr(visible));
                first = SendMessage(body.Handle, GetFirstVisibleLine, IntPtr.Zero, IntPtr.Zero).ToInt32();
                nextPage[index] = 0;
            }
            int end = Math.Min(total, first + visible);
            ranges[index].Text = end == first + 1 ? String.Format("Line {0} of {1}", end, total) :
                String.Format("Lines {0}–{1} of {2}", first + 1, end, total);
            if (manualReading[index] || end >= total) { nextPage[index] = 0; return 0; }
            if (nextPage[index] == 0)
            {
                int from = body.GetFirstCharIndexFromLine(first);
                int to = body.GetFirstCharIndexFromLine(end);
                int characters = Math.Max(1, to - from);
                nextPage[index] = now + Math.Max(3500L, Math.Min(18000L, 1300L + 70L * characters));
            }
            return (int)Math.Max(1, nextPage[index] - now);
        }

        void ResizeType()
        {
            if (visibleSources <= 0 || IsDisposed) return;
            int rowHeight = Math.Max(40, rows.ClientSize.Height / visibleSources - 46);
            int fontPixels = Math.Min(48, Math.Max(19, Math.Min(ClientSize.Width / 18, rowHeight / 3)));
            if (captionFont != null && captionFont.Size == fontPixels) return;
            Font previous = captionFont;
            captionFont = new Font("Segoe UI", fontPixels, FontStyle.Bold, GraphicsUnit.Pixel);
            foreach (var body in bodies) body.Font = captionFont;
            if (previous != null) previous.Dispose();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) expiryTimer.Dispose();
            base.Dispose(disposing);
            if (disposing)
            {
                if (captionFont != null) captionFont.Dispose();
                headingFont.Dispose();
                rangeFont.Dispose();
                idleFont.Dispose();
                toolbarFont.Dispose();
            }
        }
    }
}
