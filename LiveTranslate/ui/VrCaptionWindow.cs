using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class VrCaptionState
    {
        internal static readonly string[] Channels = { "audio", "screen", "text" };
        readonly string[] captions = new string[3];
        readonly string[] originals = new string[3], sourceLabels = new string[3];
        readonly long[] expiry = new long[3];

        internal void Present(string kind, string text, long now)
        {
            Present(kind, text, null, null, now);
        }

        internal void Present(string kind, string text, string original, string sourceLabel, long now)
        {
            int index = kind == "screen_once" ? 1 : Array.IndexOf(Channels, kind);
            if (index < 0 || String.IsNullOrWhiteSpace(text)) return;
            captions[index] = text.Trim();
            originals[index] = String.IsNullOrWhiteSpace(original) ? null : original.Trim();
            sourceLabels[index] = String.IsNullOrWhiteSpace(sourceLabel) ? null : sourceLabel.Trim();
            // Screen captions follow the screen watcher. Speech and pasted text need reading time.
            expiry[index] = kind == "screen" ? Int64.MaxValue : now + Math.Max(6000L, Math.Min(120000L, 1700L + 85L * captions[index].Length));
        }

        internal void Clear(string kind)
        {
            for (int i = 0; i < Channels.Length; i++)
                if (String.IsNullOrEmpty(kind) || String.Equals(Channels[i], kind, StringComparison.Ordinal))
                {
                    captions[i] = null;
                    originals[i] = sourceLabels[i] = null;
                    expiry[i] = 0;
                }
        }

        internal string Read(int index, long now)
        {
            if (expiry[index] <= now) captions[index] = originals[index] = sourceLabels[index] = null;
            return captions[index];
        }

        internal string Original(int index, long now) { return Read(index, now) == null ? null : originals[index]; }
        internal string SourceLabel(int index, long now) { return Read(index, now) == null ? null : sourceLabels[index]; }

        internal int NextUpdate(long now)
        {
            long next = Int64.MaxValue;
            for (int i = 0; i < Channels.Length; i++)
                if (captions[i] != null && expiry[i] > now && expiry[i] < next) next = expiry[i];
            return next == Int64.MaxValue ? 0 : (int)Math.Min(Int32.MaxValue, next - now);
        }
    }

    internal static class VrCardDrawing
    {
        internal static GraphicsPath Rounded(Rectangle bounds, int radius)
        {
            var path = new GraphicsPath();
            int d = Math.Min(radius * 2, Math.Min(bounds.Width, bounds.Height));
            if (d < 2) { path.AddRectangle(bounds); return path; }
            path.AddArc(bounds.Left, bounds.Top, d, d, 180, 90);
            path.AddArc(bounds.Right - d, bounds.Top, d, d, 270, 90);
            path.AddArc(bounds.Right - d, bounds.Bottom - d, d, d, 0, 90);
            path.AddArc(bounds.Left, bounds.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    internal sealed class VrCardButton : Button
    {
        internal string Glyph;
        internal bool Accent, Selected;
        bool hovered;
        internal VrCardButton(string glyph, string label)
        {
            Glyph = glyph; Text = label; AccessibleName = label;
            AccessibleRole = AccessibleRole.PushButton;
            Cursor = Cursors.Hand;
            FlatStyle = FlatStyle.Flat;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
        }
        protected override void OnMouseEnter(EventArgs e) { hovered = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hovered = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            Color mint = Color.FromArgb(63, 231, 195);
            Color ink = !Enabled ? Color.FromArgb(98, 111, 130) : Accent ? Color.FromArgb(7, 25, 25) : Selected ? mint : Color.FromArgb(237, 242, 249);
            Rectangle box = new Rectangle(1, 1, Width - 3, Height - 3);
            using (var path = VrCardDrawing.Rounded(box, 9))
            using (var fill = new SolidBrush(Accent && Enabled ? mint : hovered || Selected ? Color.FromArgb(34, 47, 60) : BackColor))
            using (var border = new Pen(Accent && Enabled ? mint : Text.Length == 0 ? Color.Transparent : Color.FromArgb(104, 119, 136)))
            { e.Graphics.FillPath(fill, path); e.Graphics.DrawPath(border, path); }
            int cx = Text.Length == 0 ? Width / 2 : 23, cy = Height / 2;
            using (var p = new Pen(ink, 1.8F))
            {
                p.StartCap = p.EndCap = LineCap.Round;
                if (Glyph == "close") { e.Graphics.DrawLine(p, cx - 7, cy - 7, cx + 7, cy + 7); e.Graphics.DrawLine(p, cx + 7, cy - 7, cx - 7, cy + 7); }
                else if (Glyph == "pin")
                {
                    e.Graphics.DrawLines(p, new[] { new Point(cx - 1, cy - 10), new Point(cx + 8, cy - 1), new Point(cx + 4, cy + 1), new Point(cx + 1, cy + 7), new Point(cx - 7, cy - 1), new Point(cx - 1, cy - 4), new Point(cx - 1, cy - 10) });
                    e.Graphics.DrawLine(p, cx - 4, cy + 4, cx - 10, cy + 10);
                }
                else if (Glyph == "settings")
                {
                    var teeth = new PointF[24];
                    for (int i = 0; i < teeth.Length; i++) { double a = i * Math.PI / 12; double r = i % 3 == 0 ? 8 : 11; teeth[i] = new PointF(cx + (float)(Math.Cos(a) * r), cy + (float)(Math.Sin(a) * r)); }
                    e.Graphics.DrawPolygon(p, teeth); e.Graphics.DrawEllipse(p, cx - 4, cy - 4, 8, 8);
                }
                else if (Glyph == "expand")
                {
                    e.Graphics.DrawLines(p, new[] { new Point(cx + 1, cy - 8), new Point(cx + 8, cy - 8), new Point(cx + 8, cy - 1) });
                    e.Graphics.DrawLine(p, cx + 8, cy - 8, cx + 1, cy - 1);
                    e.Graphics.DrawLines(p, new[] { new Point(cx - 1, cy + 8), new Point(cx - 8, cy + 8), new Point(cx - 8, cy + 1) });
                    e.Graphics.DrawLine(p, cx - 8, cy + 8, cx - 1, cy + 1);
                }
                else if (Glyph == "pause") { e.Graphics.DrawLine(p, cx - 4, cy - 7, cx - 4, cy + 7); e.Graphics.DrawLine(p, cx + 4, cy - 7, cx + 4, cy + 7); }
                else if (Glyph == "resume") { e.Graphics.DrawPolygon(p, new[] { new Point(cx - 4, cy - 8), new Point(cx + 7, cy), new Point(cx - 4, cy + 8) }); }
                else if (Glyph == "dashboard")
                {
                    e.Graphics.DrawLines(p, new[] { new Point(cx - 1, cy - 8), new Point(cx - 8, cy - 8), new Point(cx - 8, cy + 8), new Point(cx + 8, cy + 8), new Point(cx + 8, cy + 1) });
                    e.Graphics.DrawLine(p, cx - 1, cy + 1, cx + 9, cy - 9);
                    e.Graphics.DrawLines(p, new[] { new Point(cx + 2, cy - 9), new Point(cx + 9, cy - 9), new Point(cx + 9, cy - 2) });
                }
            }
            if (Text.Length != 0) TextRenderer.DrawText(e.Graphics, Text, Font, new Rectangle(43, 0, Width - 49, Height), ink, TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(box, -4, -4), ink, BackColor);
        }
    }

    internal sealed class VrStatusBadge : Control
    {
        internal bool Active;
        internal VrStatusBadge() { SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            Color tint = Active ? Color.FromArgb(63, 231, 195) : Color.FromArgb(151, 165, 184);
            using (var path = VrCardDrawing.Rounded(new Rectangle(1, 1, Width - 3, Height - 3), 18))
            using (var pen = new Pen(tint))
            using (var brush = new SolidBrush(tint))
            { e.Graphics.DrawPath(pen, path); e.Graphics.FillEllipse(brush, 13, Height / 2 - 4, 8, 8); }
            TextRenderer.DrawText(e.Graphics, Text, Font, new Rectangle(30, 0, Width - 39, Height), Color.FromArgb(236, 241, 248), TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
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
        static readonly Color Card = Background;
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
        [DllImport("user32.dll")]
        static extern bool ReleaseCapture();
        [DllImport("user32.dll")]
        static extern bool HideCaret(IntPtr window);
        const int GetLineCount = 0x00BA, GetFirstVisibleLine = 0x00CE, ScrollLines = 0x00B6;

        readonly VrCaptionState state;
        readonly TableLayoutPanel rows = new TableLayoutPanel();
        readonly Panel[] cards = new Panel[3];
        readonly RichTextBox[] bodies = new RichTextBox[3];
        readonly RichTextBox[] originals = new RichTextBox[3];
        readonly Label[] sourceTitles = new Label[3];
        readonly Label[] ranges = new Label[3];
        readonly long[] nextPage = new long[3];
        readonly bool[] manualReading = new bool[3];
        readonly string[] displayed = new string[3];
        readonly Label idle = new Label();
        readonly ComboBox filter = new ComboBox();
        readonly Timer expiryTimer = new Timer();
        readonly ToolTip hints = new ToolTip();
        readonly VrStatusBadge status = new VrStatusBadge();
        readonly Label inputSource = new Label();
        readonly VrCardButton pin = new VrCardButton("pin", "");
        readonly VrCardButton pause = new VrCardButton("pause", "Pause");
        readonly VrCardButton dashboard = new VrCardButton("dashboard", "Open dashboard");
        readonly VrCardButton settings = new VrCardButton("settings", "");
        readonly Font brandFont = new Font("Segoe UI", 15F, FontStyle.Bold);
        readonly Font originalFont = new Font("Segoe UI", 17F, FontStyle.Regular);
        readonly Font actionFont = new Font("Segoe UI", 10F, FontStyle.Bold);
        internal Action OpenDashboardRequested, OpenSettingsRequested, PauseRequested;
        internal Func<string> StatusProvider, InputSourceProvider;
        internal Func<bool> PausedProvider, CanPauseProvider;
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
            MinimumSize = new Size(620, 350);
            ClientSize = new Size(900, 440);
            FormBorderStyle = FormBorderStyle.None;
            Padding = new Padding(1);
            DoubleBuffered = true;
            AutoScaleDimensions = new SizeF(96F, 96F);
            AutoScaleMode = AutoScaleMode.Dpi;
            ShowInTaskbar = true;
            StartPosition = FormStartPosition.Manual;

            var toolbar = new Panel { Dock = DockStyle.Top, Height = 60, Padding = new Padding(20, 9, 15, 9), BackColor = Background };
            toolbar.Paint += delegate(object sender, PaintEventArgs e) { using (var p = new Pen(Color.FromArgb(48, 59, 74))) e.Graphics.DrawLine(p, 0, toolbar.Height - 1, toolbar.Width, toolbar.Height - 1); };
            var mark = new Panel { Bounds = new Rectangle(24, 17, 30, 28) };
            mark.Paint += DrawWave;
            var brand = new Label { Text = "LiveTranslate", Font = brandFont, ForeColor = Ink, AutoSize = false, Bounds = new Rectangle(67, 12, 181, 37), TextAlign = ContentAlignment.MiddleLeft };
            status.Bounds = new Rectangle(257, 13, 162, 35);
            status.Font = toolbarFont;
            status.AccessibleName = "Translation capture status";
            var tools = new FlowLayoutPanel { Dock = DockStyle.Right, Width = 172, WrapContents = false, FlowDirection = FlowDirection.LeftToRight, Margin = Padding.Empty, Padding = Padding.Empty };
            var expand = new VrCardButton("expand", "");
            var close = new VrCardButton("close", "");
            VrCardButton[] buttons = { pin, settings, expand, close };
            string[] labels = { "Pin window", "Settings", "Expand caption window", "Close caption window" };
            for (int i = 0; i < buttons.Length; i++)
            {
                buttons[i].Size = new Size(39, 39); buttons[i].Margin = new Padding(1, 0, 2, 0);
                buttons[i].BackColor = Background; buttons[i].AccessibleName = labels[i];
                hints.SetToolTip(buttons[i], labels[i]); tools.Controls.Add(buttons[i]);
            }
            pin.Click += delegate { TopMost = !TopMost; pin.Selected = TopMost; pin.AccessibleName = TopMost ? "Unpin window" : "Pin window"; hints.SetToolTip(pin, pin.AccessibleName); pin.Invalidate(); };
            settings.Click += delegate { if (OpenSettingsRequested != null) OpenSettingsRequested(); };
            expand.Click += delegate { MaximizedBounds = Screen.FromControl(this).WorkingArea; WindowState = WindowState == FormWindowState.Maximized ? FormWindowState.Normal : FormWindowState.Maximized; };
            close.Click += delegate { Close(); };
            toolbar.Controls.Add(tools); toolbar.Controls.Add(status); toolbar.Controls.Add(brand); toolbar.Controls.Add(mark);
            toolbar.SizeChanged += delegate { status.Visible = toolbar.ClientSize.Width >= 600; };
            toolbar.MouseDown += DragWindow; brand.MouseDown += DragWindow; mark.MouseDown += DragWindow;

            var footer = new Panel { Dock = DockStyle.Bottom, Height = 74, Padding = new Padding(23, 12, 21, 12), BackColor = Background };
            footer.Paint += delegate(object sender, PaintEventArgs e) { using (var p = new Pen(Color.FromArgb(48, 59, 74))) e.Graphics.DrawLine(p, 23, 0, footer.Width - 23, 0); };
            var actions = new FlowLayoutPanel { Dock = DockStyle.Right, Width = 305, WrapContents = false, Padding = Padding.Empty, Margin = Padding.Empty };
            pause.Size = new Size(111, 45); pause.Accent = true; pause.Font = actionFont; pause.Margin = new Padding(0, 1, 10, 0); pause.AccessibleName = "Pause translation";
            dashboard.Size = new Size(182, 45); dashboard.Font = toolbarFont; dashboard.Margin = new Padding(0, 1, 0, 0); dashboard.AccessibleName = "Open dashboard";
            pause.BackColor = dashboard.BackColor = Background;
            pause.Click += delegate { if (PauseRequested != null) PauseRequested(); RefreshCaptions(); };
            dashboard.Click += delegate { if (OpenDashboardRequested != null) OpenDashboardRequested(); };
            actions.Controls.Add(pause); actions.Controls.Add(dashboard);
            var sources = new Panel { Dock = DockStyle.Fill, Padding = Padding.Empty };
            var sourceMark = new Panel { Bounds = new Rectangle(0, 3, 30, 19) }; sourceMark.Paint += DrawWave;
            inputSource.SetBounds(40, 1, 205, 23); inputSource.Font = toolbarFont; inputSource.ForeColor = Ink; inputSource.AutoEllipsis = true;
            inputSource.AccessibleName = "Capture input";
            filter.AccessibleName = "Caption source";
            filter.DropDownStyle = ComboBoxStyle.DropDownList;
            filter.SetBounds(38, 26, 157, 23);
            filter.BackColor = Background; filter.ForeColor = Muted; filter.FlatStyle = FlatStyle.Flat;
            filter.Font = rangeFont;
            filter.Items.Add("All sources");
            filter.Items.AddRange(SourceNames);
            filter.SelectedIndex = 0;
            sources.Controls.Add(inputSource); sources.Controls.Add(sourceMark); sources.Controls.Add(filter);
            sources.SizeChanged += delegate { inputSource.Width = Math.Max(30, sources.ClientSize.Width - 40); };
            footer.Controls.Add(sources); footer.Controls.Add(actions);

            rows.Dock = DockStyle.Fill;
            rows.Padding = new Padding(17, 10, 17, 8);
            rows.ColumnCount = 1;
            rows.RowCount = 3;
            rows.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            for (int i = 0; i < cards.Length; i++)
            {
                rows.RowStyles.Add(new RowStyle(SizeType.Absolute, 0));
                Panel card = new Panel { Dock = DockStyle.Fill, Margin = new Padding(3), Padding = new Padding(0, 1, 0, 3), BackColor = Card };
                var contentPanel = new Panel { Dock = DockStyle.Fill, Padding = new Padding(8, 0, 5, 0) };
                var header = new Panel { Dock = DockStyle.Top, Height = 26 };
                var title = new Label { Dock = DockStyle.Left, AutoSize = true, Text = SourceNames[i], ForeColor = Muted, Font = toolbarFont };
                sourceTitles[i] = title;
                var range = new Label { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleRight, ForeColor = Muted, Font = rangeFont, AccessibleName = SourceNames[i] + " reading position" };
                header.Controls.Add(range);
                header.Controls.Add(title);
                ranges[i] = range;
                var viewport = new Panel { Dock = DockStyle.Fill };
                var original = new RichTextBox { Dock = DockStyle.Top, Height = 38, ReadOnly = true, BorderStyle = BorderStyle.None, BackColor = Card, ForeColor = Color.FromArgb(188, 178, 255), Font = originalFont, DetectUrls = false, WordWrap = true, ScrollBars = RichTextBoxScrollBars.Vertical, AccessibleName = SourceNames[i] + " original", Visible = false };
                original.GotFocus += delegate { HideCaret(original.Handle); };
                originals[i] = original;
                RichTextBox body = new RichTextBox { Dock = DockStyle.Top, ReadOnly = true, BorderStyle = BorderStyle.None, BackColor = Card, ForeColor = Ink, DetectUrls = false, WordWrap = true, ScrollBars = RichTextBoxScrollBars.Vertical, AccessibleName = SourceNames[i] + " translation" };
                body.GotFocus += delegate { HideCaret(body.Handle); };
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
                viewport.Controls.Add(body);
                contentPanel.Controls.Add(viewport);
                contentPanel.Controls.Add(original);
                contentPanel.Controls.Add(header);
                card.Controls.Add(contentPanel);
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
            Controls.Add(footer);
            Controls.Add(toolbar);

            expiryTimer.Tick += delegate { RefreshCaptions(); };
            filter.SelectedIndexChanged += delegate { RefreshCaptions(); };
            ResizeEnd += delegate { ResizeType(); };
            content.SizeChanged += delegate { ResizeType(); };
            Shown += delegate { RefreshCaptions(); };
            RefreshCaptions();
            ActiveControl = pin;
        }

        void DrawWave(object sender, PaintEventArgs e)
        {
            var panel = (Control)sender;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            int[] levels = { 8, 18, 26, 15, 7 };
            using (var p = new Pen(Color.FromArgb(63, 231, 195), 3))
            {
                p.StartCap = p.EndCap = LineCap.Round;
                for (int i = 0; i < levels.Length; i++)
                {
                    float h = Math.Min(panel.Height - 3, levels[i]);
                    e.Graphics.DrawLine(p, 2 + i * 6, (panel.Height - h) / 2F, 2 + i * 6, (panel.Height + h) / 2F);
                }
            }
        }

        void DragWindow(object sender, MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left || WindowState != FormWindowState.Normal) return;
            ReleaseCapture();
            SendMessage(Handle, 0x00A1, new IntPtr(2), IntPtr.Zero);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var border = new Pen(Color.FromArgb(78, 91, 109), 1.5F))
            using (var path = VrCardDrawing.Rounded(new Rectangle(1, 1, Width - 3, Height - 3), 17))
                e.Graphics.DrawPath(border, path);
        }

        protected override void OnSizeChanged(EventArgs e)
        {
            base.OnSizeChanged(e);
            if (Width < 4 || Height < 4) return;
            using (var path = VrCardDrawing.Rounded(new Rectangle(0, 0, Width, Height), 18))
            {
                Region old = Region;
                Region = new Region(path);
                if (old != null) old.Dispose();
            }
            Invalidate();
        }

        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if (m.Msg != 0x0084 || WindowState != FormWindowState.Normal) return;
            long value = m.LParam.ToInt64();
            Point p = PointToClient(new Point((short)(value & 65535), (short)((value >> 16) & 65535)));
            int edge = Math.Max(6, DeviceDpiWidth());
            bool left = p.X < edge, right = p.X >= ClientSize.Width - edge;
            bool top = p.Y < edge, bottom = p.Y >= ClientSize.Height - edge;
            if (left || right || top || bottom)
                m.Result = new IntPtr(top ? left ? 13 : right ? 14 : 12 : bottom ? left ? 16 : right ? 17 : 15 : left ? 10 : 11);
        }

        int DeviceDpiWidth() { return (int)Math.Ceiling(6F * AutoScaleFactor.Width); }

        void RefreshSessionStatus()
        {
            string value = StatusProvider == null ? "Ready" : StatusProvider() ?? "Ready";
            bool paused = PausedProvider != null && PausedProvider();
            status.Text = value;
            status.Active = !paused && (value == "Listening" || value == "Watching screen" || value == "Reading screen");
            status.Invalidate();
            inputSource.Text = InputSourceProvider == null ? "Caption window" : InputSourceProvider() ?? "Caption window";
            hints.SetToolTip(inputSource, inputSource.Text);
            pause.Text = paused ? "Resume" : "Pause";
            pause.Glyph = paused ? "resume" : "pause";
            pause.AccessibleName = paused ? "Resume translation" : "Pause translation";
            pause.Enabled = PauseRequested != null && (CanPauseProvider == null || CanPauseProvider());
            dashboard.Enabled = OpenDashboardRequested != null;
            settings.Enabled = OpenSettingsRequested != null;
            pause.Invalidate();
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
            RefreshSessionStatus();
            long now = Clock.ElapsedMilliseconds;
            int mask = 0;
            int count = 0;
            for (int i = 0; i < bodies.Length; i++)
            {
                string text = state.Read(i, now) ?? "";
                string original = state.Original(i, now) ?? "";
                if (originals[i].Text != original) originals[i].Text = original;
                string sourceLabel = state.SourceLabel(i, now);
                if (!String.IsNullOrWhiteSpace(sourceLabel))
                {
                    int separator = sourceLabel.LastIndexOf(" / ", StringComparison.Ordinal);
                    if (separator >= 0) sourceLabel = sourceLabel.Substring(separator + 3);
                }
                sourceTitles[i].Text = String.IsNullOrWhiteSpace(sourceLabel) ? SourceNames[i] : sourceLabel.Replace("\r", " ").Replace("\n", " ") + "  →  English";
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
            ResizeType();
            int delay = state.NextUpdate(now);
            if (count == 0)
            {
                string waiting = filter.SelectedIndex == 0 ? "Waiting for a translation" :
                    "Waiting for " + SourceNames[filter.SelectedIndex - 1].ToLowerInvariant() + " captions";
                idle.Text = waiting + "\r\nTurn on audio or screen translation in the dashboard.";
            }
            for (int i = 0; i < bodies.Length; i++)
            {
                if ((mask & (1 << i)) == 0) { nextPage[i] = 0; continue; }
                int due = UpdatePage(i, now);
                if (due > 0 && (delay == 0 || due < delay)) delay = due;
            }
            if (StatusProvider != null && (delay == 0 || delay > 500)) delay = 500;
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
            int rowHeight = Math.Max(30, rows.ClientSize.Height / visibleSources - 40);
            int originalHeight = 0;
            for (int i = 0; i < originals.Length; i++)
            {
                bool show = originals[i].TextLength != 0 && (visibleSources == 1 || rowHeight >= 90);
                if (originals[i].Visible != show) originals[i].Visible = show;
                Size measured = TextRenderer.MeasureText(originals[i].Text, originalFont,
                    new Size(Math.Max(100, originals[i].ClientSize.Width - 22), Int32.MaxValue), TextFormatFlags.WordBreak | TextFormatFlags.NoPadding | TextFormatFlags.TextBoxControl);
                int lines = Math.Max(1, Math.Min(2, (measured.Height + originalFont.Height - 1) / originalFont.Height));
                int height = Math.Min(originalFont.Height * lines + 5, Math.Max(originalFont.Height + 2, rowHeight / 3));
                if (originals[i].Height != height) originals[i].Height = height;
                if (show) originalHeight = Math.Max(originalHeight, height);
            }
            bool anyOriginal = false;
            for (int i = 0; i < originals.Length; i++) anyOriginal |= originals[i].Visible;
            int fontPixels = Math.Min(40, Math.Max(19, Math.Min(ClientSize.Width / 22, (rowHeight - (anyOriginal ? originalHeight : 0)) / (visibleSources > 1 ? 3 : 2))));
            if (captionFont != null && captionFont.Size == fontPixels) return;
            Font previous = captionFont;
            captionFont = new Font("Segoe UI", fontPixels, FontStyle.Bold, GraphicsUnit.Pixel);
            foreach (var body in bodies) body.Font = captionFont;
            if (previous != null) previous.Dispose();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { expiryTimer.Dispose(); hints.Dispose(); }
            base.Dispose(disposing);
            if (disposing)
            {
                if (captionFont != null) captionFont.Dispose();
                headingFont.Dispose();
                rangeFont.Dispose();
                idleFont.Dispose();
                toolbarFont.Dispose();
                brandFont.Dispose();
                originalFont.Dispose();
                actionFont.Dispose();
            }
        }
    }
}
