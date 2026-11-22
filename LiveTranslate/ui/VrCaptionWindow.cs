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
        static readonly Color Background = Color.FromArgb(19, 24, 35);
        static readonly Color Ink = Color.FromArgb(250, 251, 255);
        static readonly Color Muted = Color.FromArgb(190, 201, 220);
        static readonly Color[] SourceColors = { Color.FromArgb(133, 237, 209), Color.FromArgb(192, 181, 255), Color.FromArgb(154, 210, 253) };
        static readonly string[] SourceNames = { "Speech", "Screen", "Typed text" };

        [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "SetPropW", ExactSpelling = true)]
        static extern bool SetProp(IntPtr window, string name, IntPtr value);
        [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "RemovePropW", ExactSpelling = true)]
        static extern IntPtr RemoveProp(IntPtr window, string name);

        readonly VrCaptionState state;
        readonly TableLayoutPanel rows = new TableLayoutPanel();
        readonly Panel[] cards = new Panel[3];
        readonly RichTextBox[] bodies = new RichTextBox[3];
        readonly string[] displayed = new string[3];
        readonly Label idle = new Label();
        readonly ComboBox filter = new ComboBox();
        readonly Timer expiryTimer = new Timer();
        Font captionFont;
        readonly Font headingFont = new Font("Segoe UI", 11F, FontStyle.Bold);
        readonly Font idleFont = new Font("Segoe UI", 15F);
        readonly Font toolbarFont = new Font("Segoe UI", 10F);
        int visibleSources = -1;
        int lastSourceMask = -1;

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

            var toolbar = new TableLayoutPanel { Dock = DockStyle.Top, Height = 52, Padding = new Padding(15, 8, 15, 8), ColumnCount = 2, RowCount = 1, BackColor = Color.FromArgb(30, 37, 52) };
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
                Panel card = new Panel { Dock = DockStyle.Fill, Margin = new Padding(3), Padding = new Padding(10, 3, 6, 4), BackColor = Background };
                var title = new Label { Dock = DockStyle.Top, AutoSize = false, Height = 27, Text = SourceNames[i], ForeColor = SourceColors[i], Font = headingFont };
                RichTextBox body = new RichTextBox { Dock = DockStyle.Fill, ReadOnly = true, BorderStyle = BorderStyle.None, BackColor = Background, ForeColor = Ink, DetectUrls = false, WordWrap = true, ScrollBars = RichTextBoxScrollBars.Vertical, AccessibleName = SourceNames[i] + " translation" };
                var rail = new Panel { Dock = DockStyle.Left, Width = 3, BackColor = SourceColors[i] };
                card.Controls.Add(body);
                card.Controls.Add(title);
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
            idle.Text = "Captions will appear here.\r\nIn your headset’s PC desktop view, select this window to see them in VR.";
            var content = new Panel { Dock = DockStyle.Fill };
            content.Controls.Add(rows);
            content.Controls.Add(idle);
            Controls.Add(content);
            Controls.Add(toolbar);

            expiryTimer.Tick += delegate { RefreshCaptions(); };
            filter.SelectedIndexChanged += delegate { RefreshCaptions(); };
            ResizeEnd += delegate { ResizeType(); };
            content.SizeChanged += delegate { ResizeType(); };
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
            if (delay > 0) { expiryTimer.Interval = Math.Max(20, delay); expiryTimer.Start(); }
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
                idleFont.Dispose();
                toolbarFont.Dispose();
            }
        }
    }
}
