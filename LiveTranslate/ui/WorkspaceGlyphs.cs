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
        internal EngineIndicator() { BackColor = Color.Transparent; ForeColor = WindowTheme.Ink; AccessibleRole = AccessibleRole.StatusBar; }
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
            using (Brush brush = new SolidBrush(WindowTheme.HighContrast ? SystemColors.Window : ready ? Color.FromArgb(15,48,43) : Color.FromArgb(42,35,30)))
            using (Pen edge = new Pen(WindowTheme.HighContrast ? SystemColors.WindowText : ready ? Color.FromArgb(34,94,80) : Color.FromArgb(84,69,48)))
            { g.FillPath(brush,path); g.DrawPath(edge,path); }
            using (Brush dot = new SolidBrush(ready ? WindowTheme.Accent : WindowTheme.Warning))
                g.FillEllipse(dot, pill.Left + 9*s, pill.Top + (pill.Height - 6*s)/2, 6*s, 6*s);
            pill.X += (int)(19*s); pill.Width -= (int)(24*s);
            TextRenderer.DrawText(g, Text, Font, pill, WindowTheme.HighContrast ? SystemColors.WindowText : ForeColor, TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        }
    }

    internal sealed class AvailabilityIndicator : Label
    {
        private string state;
        internal void SetState(string value) { if (state != value) { state = value; Invalidate(); } }
        internal AvailabilityIndicator() { BackColor = Color.Transparent; ForeColor = WindowTheme.Muted; }
        protected override void OnPaint(PaintEventArgs e)
        {
            float s = e.Graphics.DpiX / 96F;
            Color dot = state == "Ready" ? WindowTheme.Accent : state == "Set up" ? WindowTheme.Warning : WindowTheme.Disabled;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (Brush point = new SolidBrush(dot)) e.Graphics.FillEllipse(point, 1, (Height - 5*s)/2, 5*s, 5*s);
            Rectangle text = new Rectangle((int)(10*s), 0, Math.Max(1, Width - (int)(11*s)), Height);
            TextRenderer.DrawText(e.Graphics, Text, Font, text, WindowTheme.HighContrast ? SystemColors.WindowText : ForeColor, TextFormatFlags.Left | TextFormatFlags.NoPadding | TextFormatFlags.EndEllipsis | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
        }
    }

    // Retain the native CheckBox keyboard, accessibility and checked-state behavior.
    internal sealed class CaptionOption : CheckBox
    {
        internal CaptionOption() { Cursor = Cursors.Hand; BackColor = WindowTheme.Card; ForeColor = WindowTheme.Muted; SetStyle(ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true); }
        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            float s = g.DpiX / 96F;
            if (BackColor.A == 255) g.Clear(WindowTheme.HighContrast ? SystemColors.Window : BackColor);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            int size = (int)Math.Ceiling(16*s);
            int wordWidth = TextRenderer.MeasureText(g, Text, Font).Width;
            int x = Anchor == AnchorStyles.Right ? Math.Max(2, Width - wordWidth - size - (int)(6*s)) : 2;
            int y = (Height - size)/2;
            Color boxColor = !Enabled ? WindowTheme.Disabled : WindowTheme.Accent;
            using (GraphicsPath check = ModernGeometry.Rounded(new RectangleF(x,y,size,size),4*s))
            using (Brush fill = new SolidBrush(Checked ? boxColor : WindowTheme.HighContrast ? SystemColors.Window : WindowTheme.Field))
            using (Pen outline = new Pen(Checked ? boxColor : Enabled ? WindowTheme.Muted : WindowTheme.Disabled)) {
                g.FillPath(fill,check); g.DrawPath(outline,check);
            }
            if (Checked) using (Pen line = new Pen(WindowTheme.AccentInk,1.8F*s) { LineJoin=LineJoin.Round, StartCap=LineCap.Round, EndCap=LineCap.Round })
                g.DrawLines(line,new[] { new PointF(x+3.5F*s,y+8*s), new PointF(x+6.5F*s,y+11*s), new PointF(x+12.5F*s,y+5*s) });
            int left = x+size+(int)(5*s);
            Color textColor = !Enabled ? WindowTheme.Disabled : WindowTheme.HighContrast ? SystemColors.WindowText : ForeColor;
            TextRenderer.DrawText(g, Text, Font, new Rectangle(left,0,Math.Max(1,Width-left),Height), textColor, TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix);
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(g, Rectangle.Inflate(ClientRectangle,-1,-1), WindowTheme.Ink, WindowTheme.HighContrast ? SystemColors.Window : BackColor);
        }
    }

    internal sealed class ComposerEntry : TextBox
    {
        private bool sizingScroll;
        internal ComposerEntry() { BackColor = WindowTheme.Field; ForeColor = WindowTheme.Ink; }
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
        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); WindowTheme.ApplyControl(this); FitScrollBar(); }
        protected override void OnSystemColorsChanged(EventArgs e)
        {
            base.OnSystemColorsChanged(e);
            BackColor = WindowTheme.Field; ForeColor = WindowTheme.Ink;
            WindowTheme.ApplyControl(this); Invalidate();
        }
        protected override void OnFontChanged(EventArgs e) { base.OnFontChanged(e); FitScrollBar(); }
        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if ((m.Msg != 0x000F && m.Msg != 0x0318) || TextLength != 0 || Focused || !IsHandleCreated) return;
            using (Graphics g = m.Msg == 0x0318 && m.WParam != IntPtr.Zero ? Graphics.FromHdc(m.WParam) : CreateGraphics())
                TextRenderer.DrawText(g, "Type or paste text to translate…", Font, ClientRectangle, WindowTheme.Muted, TextFormatFlags.Top | TextFormatFlags.Left | TextFormatFlags.NoPrefix | TextFormatFlags.WordBreak);
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
            ForeColor = WindowTheme.Accent;
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
            Color lavender = WindowTheme.HighContrast ? SystemColors.WindowText : ForeColor;
            if (kind == Kind.Brand)
            {
                using (GraphicsPath box = ModernGeometry.Rounded(new RectangleF(0.5F, 0.5F, 31F, 31F), 8F))
                using (Brush fill = new SolidBrush(WindowTheme.HighContrast ? SystemColors.Window : Color.FromArgb(15,48,43)))
                using (Pen edge = new Pen(lavender,1.2F)) { g.FillPath(fill, box); g.DrawPath(edge,box); }
                using (Pen line = new Pen(lavender,1.9F) { StartCap=LineCap.Round, EndCap=LineCap.Round, LineJoin=LineJoin.Round }) {
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

    // These are decorative paths; actionable parents retain their native button
    // keyboard and accessibility semantics. No icon fonts or external assets.
    internal sealed class WorkspaceGlyph : Control
    {
        internal enum Kind { Brand, Live, History, Audio, Settings, Pause, Stop, Save, Pin, Expand, Screen }
        private Kind symbol;
        internal Kind Symbol { get { return symbol; } set { if (symbol != value) { symbol = value; Invalidate(); } } }
        internal WorkspaceGlyph()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.SupportsTransparentBackColor, true);
            BackColor = Color.Transparent;
            ForeColor = WindowTheme.Muted;
            Size = new Size(24, 24);
            TabStop = false;
            AccessibleRole = AccessibleRole.None;
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            Draw(e.Graphics, ClientRectangle, symbol, Enabled ? ForeColor : WindowTheme.Disabled);
        }
        internal static void Draw(Graphics graphics, RectangleF bounds, Kind kind, Color color)
        {
            float size = Math.Min(bounds.Width, bounds.Height);
            if (size < 2F) return;
            GraphicsState state = graphics.Save();
            try
            {
                graphics.TranslateTransform(bounds.Left + (bounds.Width-size)/2F, bounds.Top + (bounds.Height-size)/2F);
                graphics.ScaleTransform(size/24F,size/24F);
                graphics.SmoothingMode = SmoothingMode.AntiAlias;
                if (WindowTheme.HighContrast) color = SystemColors.WindowText;
                using (Pen pen = new Pen(color,1.65F) { StartCap=LineCap.Round, EndCap=LineCap.Round, LineJoin=LineJoin.Round })
                using (Brush fill = new SolidBrush(color))
                {
                    switch (kind)
                    {
                        case Kind.Brand:
                            graphics.DrawLines(pen,new[] { new PointF(5,5),new PointF(2,5),new PointF(2,19),new PointF(5,19) });
                            graphics.DrawLines(pen,new[] { new PointF(19,5),new PointF(22,5),new PointF(22,19),new PointF(19,19) });
                            for (int i=0;i<5;i++) { float h=new[] { 5F,11F,17F,9F,5F }[i]; graphics.DrawLine(pen,6+i*3,12-h/2F,6+i*3,12+h/2F); }
                            break;
                        case Kind.Live:
                        case Kind.Screen:
                            using (GraphicsPath box = ModernGeometry.Rounded(new RectangleF(3,4,18,13),2F)) graphics.DrawPath(pen,box);
                            graphics.DrawLine(pen,12,17,12,21); graphics.DrawLine(pen,8,21,16,21);
                            if (kind == Kind.Live) graphics.DrawLines(pen,new[] { new PointF(6,11),new PointF(9,11),new PointF(11,8),new PointF(13,13),new PointF(15,10),new PointF(18,10) });
                            break;
                        case Kind.History:
                            graphics.DrawArc(pen,4,4,16,16,-100,300);
                            graphics.DrawLines(pen,new[] { new PointF(3,4),new PointF(3,9),new PointF(8,9) });
                            graphics.DrawLines(pen,new[] { new PointF(12,7),new PointF(12,12),new PointF(15.5F,14) });
                            break;
                        case Kind.Audio:
                            for (int i=0;i<5;i++) { float h=new[] { 5F,11F,18F,10F,5F }[i]; graphics.DrawLine(pen,4+i*4,12-h/2F,4+i*4,12+h/2F); }
                            break;
                        case Kind.Settings:
                            for (int i=0;i<3;i++)
                            {
                                float y=6+i*6, x=i==1?15:8;
                                graphics.DrawLine(pen,3,y,x-2.5F,y); graphics.DrawEllipse(pen,x-2.5F,y-2.5F,5,5); graphics.DrawLine(pen,x+2.5F,y,21,y);
                            }
                            break;
                        case Kind.Pause:
                            using (GraphicsPath a=ModernGeometry.Rounded(new RectangleF(6,5,4,14),1F)) graphics.FillPath(fill,a);
                            using (GraphicsPath b=ModernGeometry.Rounded(new RectangleF(14,5,4,14),1F)) graphics.FillPath(fill,b);
                            break;
                        case Kind.Stop:
                            using (GraphicsPath box=ModernGeometry.Rounded(new RectangleF(5,5,14,14),2F)) graphics.FillPath(fill,box);
                            break;
                        case Kind.Save:
                            graphics.DrawLines(pen,new[] { new PointF(4,3),new PointF(17,3),new PointF(21,7),new PointF(21,21),new PointF(3,21),new PointF(3,3),new PointF(4,3) });
                            graphics.DrawLines(pen,new[] { new PointF(7,3),new PointF(7,9),new PointF(16,9),new PointF(16,3) });
                            graphics.DrawLines(pen,new[] { new PointF(7,21),new PointF(7,14),new PointF(17,14),new PointF(17,21) });
                            break;
                        case Kind.Pin:
                            graphics.DrawLines(pen,new[] { new PointF(9,3),new PointF(17,3),new PointF(16,10),new PointF(19,14),new PointF(6,14),new PointF(9,10),new PointF(9,3) });
                            graphics.DrawLine(pen,12.5F,14,12.5F,21);
                            break;
                        case Kind.Expand:
                            graphics.DrawLines(pen,new[] { new PointF(4,9),new PointF(4,4),new PointF(9,4) });
                            graphics.DrawLines(pen,new[] { new PointF(15,4),new PointF(20,4),new PointF(20,9) });
                            graphics.DrawLines(pen,new[] { new PointF(20,15),new PointF(20,20),new PointF(15,20) });
                            graphics.DrawLines(pen,new[] { new PointF(9,20),new PointF(4,20),new PointF(4,15) });
                            break;
                    }
                }
            }
            finally { graphics.Restore(state); }
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
            BackColor = WindowTheme.Card;
            ForeColor = WindowTheme.Ink;
            action.Text = "Set up language files";
            action.Size = new Size(158, 32);
            action.Font = new Font("Segoe UI", 9F);
            action.BackColor = WindowTheme.Accent;
            action.ForeColor = WindowTheme.AccentInk;
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
                WindowTheme.Muted, TextFormatFlags.HorizontalCenter | TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix);
        }

        private static void DrawConversation(Graphics g)
        {
            Color dark = WindowTheme.HighContrast ? SystemColors.Window : Color.FromArgb(24, 45, 48);
            Color mint = WindowTheme.Accent;
            using (Brush glow = new SolidBrush(WindowTheme.HighContrast ? SystemColors.Window : Color.FromArgb(14, 35, 38)))
                g.FillEllipse(glow, 14, 5, 171, 88);
            using (Brush stipple = new SolidBrush(WindowTheme.Border))
                for (int x = 0; x < 4; x++)
                    for (int y = 0; y < 3; y++)
                        g.FillEllipse(stipple, 150 + x * 6, 11 + y * 6, 1.8F, 1.8F);

            using (GraphicsPath screen = ModernGeometry.Rounded(new RectangleF(33, 14, 103, 65), 8))
            using (Brush face = new SolidBrush(WindowTheme.Field))
            using (Pen edge = new Pen(WindowTheme.Border, 1.5F))
            {
                g.FillPath(face, screen);
                g.DrawPath(edge, screen);
                g.DrawLine(edge, 34, 29, 135, 29);
            }
            using (Brush dot = new SolidBrush(WindowTheme.Muted))
                for (int i = 0; i < 3; i++) g.FillEllipse(dot, 41 + i * 5, 20, 2.5F, 2.5F);
            using (Pen wave = new Pen(mint, 3.2F) { StartCap = LineCap.Round, EndCap = LineCap.Round })
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
            using (Pen line = new Pen(WindowTheme.Ink, 2.6F) { StartCap = LineCap.Round, EndCap = LineCap.Round })
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
