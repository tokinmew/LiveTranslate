using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace LiveTranslate
{
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
            Color lavender = Color.FromArgb(184, 178, 255);
            if (kind == Kind.Brand)
            {
                using (GraphicsPath box = ModernGeometry.Rounded(new RectangleF(0.5F, 0.5F, 31F, 31F), 8F))
                using (Brush fill = new SolidBrush(Color.FromArgb(83, 67, 169))) g.FillPath(fill, box);
                PaintWave(g, Color.White, 16F);
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
            action.BackColor = Color.FromArgb(85, 69, 172);
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
                Color.FromArgb(79, 89, 111), TextFormatFlags.HorizontalCenter | TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix);
        }

        // A sound wave entering one caption bubble and three lines leaving the other.
        private static void DrawConversation(Graphics g)
        {
            using (Pen orbit = new Pen(Color.FromArgb(224, 222, 240), 1.2F))
            {
                g.DrawArc(orbit, 10, 20, 174, 63, 183, 126);
                g.DrawArc(orbit, 10, 20, 174, 63, 4, 137);
            }
            using (Brush dot = new SolidBrush(Color.FromArgb(159, 144, 216))) g.FillEllipse(dot, 16, 59, 5, 5);
            using (Brush dot = new SolidBrush(Color.FromArgb(73, 163, 142))) g.FillEllipse(dot, 174, 35, 6, 6);
            using (Brush dot = new SolidBrush(Color.FromArgb(222, 160, 112))) g.FillEllipse(dot, 155, 12, 4, 4);

            Color lilac = Color.FromArgb(222, 216, 249), plum = Color.FromArgb(80, 65, 159);
            using (GraphicsPath bubble = ModernGeometry.Rounded(new RectangleF(33, 13, 77, 50), 12))
            using (Brush fill = new SolidBrush(lilac))
            {
                g.FillPolygon(fill, new[] { new PointF(47, 55), new PointF(45, 73), new PointF(66, 56) });
                g.FillPath(fill, bubble);
            }
            using (Pen wave = new Pen(plum, 3.6F) { StartCap = LineCap.Round, EndCap = LineCap.Round })
            {
                int[] bars = { 5, 13, 22, 12, 18, 7 };
                for (int i = 0; i < bars.Length; i++)
                    g.DrawLine(wave, 51 + i * 7, 38 - bars[i] / 2F, 51 + i * 7, 38 + bars[i] / 2F);
            }
            using (GraphicsPath bubble = ModernGeometry.Rounded(new RectangleF(83, 42, 76, 43), 11))
            using (Brush fill = new SolidBrush(plum))
            {
                g.FillPolygon(fill, new[] { new PointF(128, 79), new PointF(146, 94), new PointF(144, 77) });
                g.FillPath(fill, bubble);
            }
            using (Pen lines = new Pen(Color.White, 3.3F) { StartCap = LineCap.Round, EndCap = LineCap.Round })
            {
                g.DrawLine(lines, 98, 57, 145, 57);
                g.DrawLine(lines, 98, 68, 130, 68);
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) { heading.Dispose(); detail.Dispose(); }
            base.Dispose(disposing);
        }
    }
}
