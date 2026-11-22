using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class EngineIndicator : Label
    {
        private bool ready;
        internal bool Ready { set { if (ready != value) { ready = value; Invalidate(); } } }
        internal EngineIndicator() { BackColor = Color.Transparent; AccessibleRole = AccessibleRole.StatusBar; }
        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            float s = g.DpiX / 96F;
            int w = Math.Min(Width - 1, TextRenderer.MeasureText(g, Text, Font).Width + (int)(28*s));
            int h = Math.Min(Height - 1, (int)Math.Ceiling(26*s));
            if (w <= 0 || h <= 0) return;
            Rectangle pill = new Rectangle(Width-w, (Height-h)/2, w-1, h);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (GraphicsPath path = ModernGeometry.Rounded(pill, h/2F))
            using (Brush brush = new SolidBrush(ready ? Color.FromArgb(208,235,222) : Color.FromArgb(242,232,208))) g.FillPath(brush,path);
            using (Brush dot = new SolidBrush(ready ? Color.FromArgb(15,115,85) : Color.FromArgb(148,99,22)))
                g.FillEllipse(dot, pill.Left + 9*s, pill.Top + (pill.Height - 6*s)/2, 6*s, 6*s);
            pill.X += (int)(19*s); pill.Width -= (int)(24*s);
            TextRenderer.DrawText(g, Text, Font, pill, ForeColor, TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        }
    }

    internal sealed class AvailabilityIndicator : Label
    {
        private string state;
        internal void SetState(string value) { if (state != value) { state = value; Invalidate(); } }
        internal AvailabilityIndicator() { BackColor = Color.Transparent; }
        protected override void OnPaint(PaintEventArgs e)
        {
            float s = e.Graphics.DpiX / 96F;
            Color dot = state == "Ready" ? Color.FromArgb(116,225,194) : state == "Set up" ? Color.FromArgb(234,189,120) : Color.FromArgb(148,174,168);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (Brush point = new SolidBrush(dot)) e.Graphics.FillEllipse(point, 1, (Height - 5*s)/2, 5*s, 5*s);
            Rectangle text = new Rectangle((int)(10*s), 0, Math.Max(1, Width - (int)(11*s)), Height);
            TextRenderer.DrawText(e.Graphics, Text, Font, text, ForeColor, TextFormatFlags.Left | TextFormatFlags.NoPadding | TextFormatFlags.EndEllipsis | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
        }
    }

    // Retain the native CheckBox keyboard, accessibility and checked-state behavior.
    internal sealed class CaptionOption : CheckBox
    {
        internal CaptionOption() { Cursor = Cursors.Hand; SetStyle(ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true); }
        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            float s = g.DpiX / 96F;
            g.Clear(BackColor);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            int size = (int)Math.Ceiling(16*s);
            int wordWidth = TextRenderer.MeasureText(g, Text, Font).Width;
            int x = Anchor == AnchorStyles.Right ? Math.Max(2, Width - wordWidth - size - (int)(6*s)) : 2;
            int y = (Height - size)/2;
            using (GraphicsPath check = ModernGeometry.Rounded(new RectangleF(x,y,size,size),4*s))
            using (Brush fill = new SolidBrush(Checked ? Color.FromArgb(17,107,96) : BackColor))
            using (Pen outline = new Pen(Checked ? Color.FromArgb(17,107,96) : Color.FromArgb(105,130,123))) {
                g.FillPath(fill,check); g.DrawPath(outline,check);
            }
            if (Checked) using (Pen line = new Pen(Color.White,1.8F*s) { LineJoin=LineJoin.Round, StartCap=LineCap.Round, EndCap=LineCap.Round })
                g.DrawLines(line,new[] { new PointF(x+3.5F*s,y+8*s), new PointF(x+6.5F*s,y+11*s), new PointF(x+12.5F*s,y+5*s) });
            int left = x+size+(int)(5*s);
            TextRenderer.DrawText(g, Text, Font, new Rectangle(left,0,Math.Max(1,Width-left),Height), ForeColor, TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix);
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(g, Rectangle.Inflate(ClientRectangle,-1,-1), ForeColor, BackColor);
        }
    }

    internal sealed class ComposerEntry : TextBox
    {
        private bool sizingScroll;
        private void FitScrollBar()
        {
            if (!IsHandleCreated || sizingScroll || !Multiline || ClientSize.Height < 1) return;
            sizingScroll = true;
            try {
                int rows = Math.Max(1, ClientSize.Height / Font.Height);
                bool overflow = TextLength > 0 && GetLineFromCharIndex(TextLength) + 1 > rows;
                ScrollBars desired = overflow ? ScrollBars.Vertical : ScrollBars.None;
                if (ScrollBars != desired) {
                    int start = SelectionStart, length = SelectionLength;
                    ScrollBars = desired;
                    Select(start,length);
                }
            } finally { sizingScroll = false; }
        }
        protected override void OnSizeChanged(EventArgs e) { base.OnSizeChanged(e); FitScrollBar(); }
        protected override void OnTextChanged(EventArgs e) { base.OnTextChanged(e); FitScrollBar(); }
        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); FitScrollBar(); }
        protected override void OnFontChanged(EventArgs e) { base.OnFontChanged(e); FitScrollBar(); }
        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if ((m.Msg != 0x000F && m.Msg != 0x0318) || TextLength != 0 || Focused || !IsHandleCreated) return;
            using (Graphics g = m.Msg == 0x0318 && m.WParam != IntPtr.Zero ? Graphics.FromHdc(m.WParam) : CreateGraphics())
                TextRenderer.DrawText(g, "Type or paste text to translate…", Font, ClientRectangle, Color.FromArgb(88,111,103), TextFormatFlags.Top | TextFormatFlags.Left | TextFormatFlags.NoPrefix | TextFormatFlags.WordBreak);
        }
    }

    internal sealed class DashboardGlyph : Control
    {
        internal enum Kind { Brand, Screen, Audio }
        private readonly Kind kind;
        internal DashboardGlyph(Kind kind)
        {
            this.kind = kind;
            SetStyle(ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.SupportsTransparentBackColor, true);
            BackColor = Color.Transparent;
            TabStop = false;
            AccessibleRole = AccessibleRole.None;
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            float scale = Math.Min(Width, Height) / 32F;
            if (scale <= 0) return;
            g.ScaleTransform(scale, scale);
            Color lavender = Color.FromArgb(116,225,194);
            if (kind == Kind.Brand)
            {
                using (GraphicsPath box = ModernGeometry.Rounded(new RectangleF(0.5F, 0.5F, 31F, 31F), 8F))
                using (Brush fill = new SolidBrush(Color.FromArgb(17, 107, 96))) g.FillPath(fill, box);
                using (Pen line = new Pen(Color.FromArgb(213,255,237),1.9F) { StartCap=LineCap.Round, EndCap=LineCap.Round, LineJoin=LineJoin.Round }) {
                    g.DrawLines(line,new[] { new Point(6,20), new Point(6,11), new Point(10,11) });
                    g.DrawLines(line,new[] { new Point(26,12), new Point(26,21), new Point(22,21) });
                    g.DrawLine(line,11,14,11,18); g.DrawLine(line,15,8,15,24); g.DrawLine(line,19,11,19,21); g.DrawLine(line,22,14,22,17);
                }
            }
            else if (kind == Kind.Screen)
            {
                using (Pen pen = new Pen(lavender, 2.2F))
                using (GraphicsPath monitor = ModernGeometry.Rounded(new RectangleF(3.5F, 5.5F, 25F, 17F), 2.5F))
                {
                    g.DrawPath(pen, monitor);
                    g.DrawLine(pen, 16F, 22F, 16F, 26F);
                    g.DrawLine(pen, 10F, 26F, 22F, 26F);
                }
            }
            else PaintWave(g, lavender, 16F);
        }
        internal static void PaintWave(Graphics g, Color color, float y)
        {
            int[] lengths = { 5, 12, 19, 10, 5 };
            using (Pen line = new Pen(color, 2.4F) { StartCap = LineCap.Round, EndCap = LineCap.Round })
                for (int i = 0; i < lengths.Length; i++)
                    g.DrawLine(line, 6 + 5 * i, y - lengths[i] / 2F, 6 + 5 * i, y + lengths[i] / 2F);
        }
    }

    internal sealed class EmptyTranscript : Label
    {
        private readonly Font heading = new Font("Segoe UI", 14F, FontStyle.Bold);
        private readonly Font detail = new Font("Segoe UI", 10F);
        private string hint = "Turn on a capture source or paste text below.";
        internal string Hint { get { return hint; } set { if (hint != value) { hint = value; AccessibleDescription = value; ArrangeAction(); Invalidate(); } } }

        private readonly Button action = new ModernButton();
        private bool showSetup;
        internal bool ShowSetup { set { showSetup = value; action.Visible = value; ArrangeAction(); Invalidate(); } }
        internal EmptyTranscript(EventHandler setup)
        {
            AccessibleDescription = hint;
            action.Text = "Set up language files";
            action.Size = new Size(158, 32);
            action.Font = new Font("Segoe UI", 9F);
            action.BackColor = Color.FromArgb(17, 107, 96);
            action.ForeColor = Color.White;
            action.FlatAppearance.BorderColor = action.BackColor;
            action.Click += setup;
            action.Visible = false;
            Controls.Add(action);
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            TabStop = false;
        }

        protected override void OnSizeChanged(EventArgs e) { base.OnSizeChanged(e); ArrangeAction(); }
        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); ArrangeAction(); }

        private void ArrangeAction()
        {
            if (!showSetup || !IsHandleCreated || Width < 1 || Height < 1) return;
            using (Graphics g = CreateGraphics())
            {
                int titleHeight, hintHeight, graphicsHeight, top, gap;
                float scale;
                Measure(g, out titleHeight, out hintHeight, out graphicsHeight, out top, out gap, out scale);
                int buttonGap = (int)(10 * g.DpiX / 96F);
                action.Location = new Point(Math.Max(0, (Width - action.Width) / 2),
                    Math.Max(0, Math.Min(Height - action.Height, top + graphicsHeight + gap + titleHeight + hintHeight + buttonGap)));
            }
        }

        private void Measure(Graphics g, out int titleHeight, out int hintHeight, out int graphicHeight, out int top, out int gap, out float scale)
        {
            float dpi = g.DpiX / 96F;
            titleHeight = (int)Math.Ceiling(heading.GetHeight(g) * 1.6F);
            int textWidth = Math.Max(1, Width - 24);
            hintHeight = TextRenderer.MeasureText(g, hint, detail, new Size(textWidth, Int32.MaxValue),
                TextFormatFlags.HorizontalCenter | TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix).Height;
            int buttonGap = showSetup ? (int)(10 * dpi) : 0;
            int contentHeight = Height - (showSetup ? action.Height + buttonGap : 0);
            int room = contentHeight - titleHeight - hintHeight - (int)(10 * dpi);
            scale = Math.Min(dpi, Math.Min((Width - 20) / 195F, room / 100F));
            graphicHeight = scale >= .46F ? (int)(100F * scale) : 0;
            gap = graphicHeight > 0 ? (int)(10F * dpi) : 0;
            top = Math.Max(0, (contentHeight - titleHeight - hintHeight - graphicHeight - gap) / 2);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            int titleHeight, hintHeight, graphicHeight, top, gap;
            float scale;
            Measure(g, out titleHeight, out hintHeight, out graphicHeight, out top, out gap, out scale);
            int textWidth = Math.Max(1, Width - 24);
            if (graphicHeight > 0)
            {
                GraphicsState state = g.Save();
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.TranslateTransform((Width - 195 * scale) / 2, top);
                g.ScaleTransform(scale, scale);
                DrawConversation(g);
                g.Restore(state);
                top += graphicHeight + gap;
            }
            TextRenderer.DrawText(g, Text, heading, new Rectangle(0, top, Width, titleHeight), ForeColor,
                TextFormatFlags.VerticalCenter | TextFormatFlags.HorizontalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis);
            TextRenderer.DrawText(g, hint, detail, new Rectangle(12, top + titleHeight, textWidth, hintHeight + 2),
                Color.FromArgb(74, 99, 101), TextFormatFlags.HorizontalCenter | TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix);
        }

        private static void DrawConversation(Graphics g)
        {
            Color dark = Color.FromArgb(23, 65, 62);
            Color mint = Color.FromArgb(119, 225, 191);
            using (Brush glow = new SolidBrush(Color.FromArgb(237, 248, 242)))
                g.FillEllipse(glow, 14, 5, 171, 88);
            using (Brush stipple = new SolidBrush(Color.FromArgb(163, 207, 185)))
                for (int x = 0; x < 4; x++)
                    for (int y = 0; y < 3; y++)
                        g.FillEllipse(stipple, 150 + x * 6, 11 + y * 6, 1.8F, 1.8F);

            using (GraphicsPath screen = ModernGeometry.Rounded(new RectangleF(33, 14, 103, 65), 8))
            using (Brush face = new SolidBrush(Color.White))
            using (Pen edge = new Pen(Color.FromArgb(125, 162, 148), 1.5F))
            {
                g.FillPath(face, screen);
                g.DrawPath(edge, screen);
                g.DrawLine(edge, 34, 29, 135, 29);
            }
            using (Brush dot = new SolidBrush(Color.FromArgb(126, 167, 148)))
                for (int i = 0; i < 3; i++) g.FillEllipse(dot, 41 + i * 5, 20, 2.5F, 2.5F);
            using (Pen wave = new Pen(Color.FromArgb(28, 121, 101), 3.2F) { StartCap = LineCap.Round, EndCap = LineCap.Round })
            {
                int[] bars = { 4, 10, 18, 9, 24, 15, 7, 13, 4 };
                for (int i = 0; i < bars.Length; i++)
                    g.DrawLine(wave, 44 + i * 6, 53 - bars[i] / 2F, 44 + i * 6, 53 + bars[i] / 2F);
            }
            using (GraphicsPath caption = ModernGeometry.Rounded(new RectangleF(90, 47, 76, 37), 7))
            using (Brush fill = new SolidBrush(dark))
            {
                g.FillPath(fill, caption);
                g.FillPolygon(fill, new[] { new PointF(144, 81), new PointF(155, 92), new PointF(155, 81) });
            }
            using (Pen line = new Pen(Color.White, 2.6F) { StartCap = LineCap.Round, EndCap = LineCap.Round })
            {
                g.DrawLine(line, 102, 60, 151, 60);
                line.Color = mint;
                g.DrawLine(line, 102, 70, 134, 70);
            }
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing) { heading.Dispose(); detail.Dispose(); }
            base.Dispose(disposing);
        }
    }
}
