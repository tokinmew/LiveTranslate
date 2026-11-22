using System;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal static class ModernGeometry
    {
        internal static GraphicsPath Rounded(RectangleF bounds, float radius)
        {
            GraphicsPath path = new GraphicsPath();
            float diameter = Math.Max(0, Math.Min(radius * 2F, Math.Min(bounds.Width, bounds.Height)));
            if (diameter < 1F) { path.AddRectangle(bounds); return path; }
            path.AddArc(bounds.Left, bounds.Top, diameter, diameter, 180F, 90F);
            path.AddArc(bounds.Right - diameter, bounds.Top, diameter, diameter, 270F, 90F);
            path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0F, 90F);
            path.AddArc(bounds.Left, bounds.Bottom - diameter, diameter, diameter, 90F, 90F);
            path.CloseFigure();
            return path;
        }
    }

    internal sealed class ModernSwitch : Control
    {
        private bool isChecked;
        private Color accent = Color.FromArgb(103, 219, 190);
        public event EventHandler CheckedChanged;

        public ModernSwitch()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.SupportsTransparentBackColor | ControlStyles.Selectable, true);
            BackColor = Color.Transparent;
            Size = new Size(60, 30);
            MinimumSize = new Size(38, 22);
            TabStop = true;
            Cursor = Cursors.Hand;
            AccessibleRole = AccessibleRole.CheckButton;
            AccessibleName = "Switch";
        }

        [DefaultValue(false)]
        public bool Checked
        {
            get { return isChecked; }
            set
            {
                if (isChecked == value) return;
                isChecked = value;
                Invalidate();
                AccessibilityNotifyClients(AccessibleEvents.StateChange, -1);
                EventHandler handler = CheckedChanged;
                if (handler != null) handler(this, EventArgs.Empty);
            }
        }

        public Color AccentColor
        {
            get { return accent; }
            set { accent = value; Invalidate(); }
        }

        protected override Size DefaultSize { get { return new Size(60, 30); } }
        protected override void OnClick(EventArgs e)
        {
            if (!Enabled) return;
            Checked = !Checked;
            base.OnClick(e);
        }
        protected override bool IsInputKey(Keys keyData)
        {
            Keys key = keyData & Keys.KeyCode;
            return key == Keys.Space || key == Keys.Enter || base.IsInputKey(keyData);
        }
        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Space || e.KeyCode == Keys.Enter) { e.Handled = true; e.SuppressKeyPress = true; }
            base.OnKeyDown(e);
        }
        protected override void OnKeyUp(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Space || e.KeyCode == Keys.Enter) { if (Enabled) OnClick(EventArgs.Empty); e.Handled = true; }
            base.OnKeyUp(e);
        }
        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Invalidate(); }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            if (Width < 4 || Height < 4) return;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            RectangleF track = new RectangleF(1F, 1F, Width - 2F, Height - 2F);
            Color trackColor = Enabled ? (Checked ? accent : Color.FromArgb(77, 102, 103)) : Color.FromArgb(60, 82, 83);
            using (GraphicsPath path = ModernGeometry.Rounded(track, track.Height / 2F))
            using (Brush brush = new SolidBrush(trackColor)) e.Graphics.FillPath(brush, path);
            float inset = Math.Max(3F, Height * 0.12F);
            float diameter = Math.Max(4F, Height - inset * 2F);
            float left = Checked ? Width - inset - diameter : inset;
            using (Brush shadow = new SolidBrush(Color.FromArgb(30, 0, 0, 0))) e.Graphics.FillEllipse(shadow, left, inset + 1F, diameter, diameter);
            Color thumb = !Enabled ? Color.FromArgb(157, 179, 176) : Checked ? Color.FromArgb(17, 65, 60) : Color.White;
            using (Brush knob = new SolidBrush(thumb)) e.Graphics.FillEllipse(knob, left, inset, diameter, diameter);
            if (Focused && ShowFocusCues)
            {
                RectangleF focus = new RectangleF(0.7F, 0.7F, Width - 1.4F, Height - 1.4F);
                using (GraphicsPath path = ModernGeometry.Rounded(focus, focus.Height / 2F))
                using (Pen pen = new Pen(Color.FromArgb(231, 244, 250), 1F)) { pen.DashStyle = DashStyle.Dot; e.Graphics.DrawPath(pen, path); }
            }
        }

        protected override AccessibleObject CreateAccessibilityInstance() { return new SwitchAccessibleObject(this); }
        private sealed class SwitchAccessibleObject : ControlAccessibleObject
        {
            private readonly ModernSwitch owner;
            public SwitchAccessibleObject(ModernSwitch owner) : base(owner) { this.owner = owner; }
            public override AccessibleRole Role { get { return AccessibleRole.CheckButton; } }
            public override string DefaultAction { get { return owner.Checked ? "Turn off" : "Turn on"; } }
            public override string Value { get { return owner.Checked ? "On" : "Off"; } }
            public override AccessibleStates State
            {
                get
                {
                    AccessibleStates state = base.State | AccessibleStates.Focusable;
                    if (owner.Checked) state |= AccessibleStates.Checked;
                    if (!owner.Enabled) state |= AccessibleStates.Unavailable;
                    return state;
                }
            }
            public override void DoDefaultAction() { if (owner.Enabled) owner.OnClick(EventArgs.Empty); }
        }
    }

    internal sealed class ModernCard : Panel
    {
        private Color fill = Color.FromArgb(25, 39, 60);
        private Color border = Color.FromArgb(43, 60, 81);
        private int radius = 14;
        public ModernCard()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.SupportsTransparentBackColor, true);
            BackColor = Color.Transparent;
            Padding = new Padding(16);
        }
        public Color FillColor { get { return fill; } set { fill = value; Invalidate(true); } }
        public Color BorderColor { get { return border; } set { border = value; Invalidate(); } }
        [DefaultValue(14)]
        public int CornerRadius { get { return radius; } set { radius = Math.Max(0, Math.Min(64, value)); Invalidate(true); } }
        protected override void OnPaintBackground(PaintEventArgs e)
        {
            base.OnPaintBackground(e);
            if (Width < 2 || Height < 2) return;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            float scale = e.Graphics.DpiX / 96F;
            using (GraphicsPath path = ModernGeometry.Rounded(new RectangleF(0.5F, 0.5F, Width - 1F, Height - 1F), radius * scale))
            using (Brush brush = new SolidBrush(fill)) e.Graphics.FillPath(brush, path);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            if (Width < 2 || Height < 2 || border.A == 0) return;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            float scale = e.Graphics.DpiX / 96F;
            using (GraphicsPath path = ModernGeometry.Rounded(new RectangleF(0.5F, 0.5F, Width - 1F, Height - 1F), radius * scale))
            using (Pen pen = new Pen(border, 1F)) e.Graphics.DrawPath(pen, path);
        }
    }

    internal enum ButtonSymbol { None, Headset, Settings, Arrow }

    internal class ModernButton : Button
    {
        private bool hovered, pressed;
        public bool IsPicker { get; set; }
        internal ButtonSymbol Symbol { get; set; }
        public ModernButton()
        {
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            UseVisualStyleBackColor = false;
            Cursor = Cursors.Hand;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        }
        protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); hovered = true; Invalidate(); }
        protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); hovered = false; Invalidate(); }
        protected override void OnMouseDown(MouseEventArgs e) { base.OnMouseDown(e); pressed = e.Button == MouseButtons.Left; Invalidate(); }
        protected override void OnMouseUp(MouseEventArgs e) { base.OnMouseUp(e); pressed = false; Invalidate(); }
        protected override void OnMouseCaptureChanged(EventArgs e) { base.OnMouseCaptureChanged(e); if (!Capture) pressed = false; Invalidate(); }
        private Color Surround()
        {
            for (Control owner = Parent; owner != null; owner = owner.Parent)
            {
                ModernCard card = owner as ModernCard;
                if (card != null) return card.FillColor;
                if (owner.BackColor.A == 255) return owner.BackColor;
            }
            return SystemColors.Control;
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            if (Width < 3 || Height < 3) return;
            Color surround = Surround(), fill = BackColor, text = ForeColor, outline = FlatAppearance.BorderColor;
            if (!Enabled)
            {
                bool light = surround.GetBrightness() > .6F;
                fill = light ? Color.FromArgb(241, 245, 243) : Color.FromArgb(48, 70, 71);
                text = light ? Color.FromArgb(95, 112, 108) : Color.FromArgb(183, 200, 194);
                outline = light ? Color.FromArgb(217, 226, 221) : Color.FromArgb(73, 95, 94);
            }
            else if (hovered || pressed)
            {
                if (fill.GetBrightness() > .5F) fill = ControlPaint.Dark(fill, pressed ? .15F : .06F);
                else fill = ControlPaint.Light(fill, pressed ? .16F : .08F);
            }
            e.Graphics.Clear(surround);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            float scale = e.Graphics.DpiX / 96F;
            using (GraphicsPath path = ModernGeometry.Rounded(new RectangleF(.5F, .5F, Width - 1F, Height - 1F), 6F * scale))
            using (Brush brush = new SolidBrush(fill))
            using (Pen pen = new Pen(outline))
            {
                e.Graphics.FillPath(brush, path);
                e.Graphics.DrawPath(pen, path);
            }
            Rectangle bounds = Rectangle.Inflate(ClientRectangle, -3, -2);
            TextFormatFlags align = IsPicker ? TextFormatFlags.Left : TextFormatFlags.HorizontalCenter;
            if (IsPicker)
            {
                int inset = (int)(10 * scale), end = Width - (int)(17 * scale);
                bounds.X += inset;
                bounds.Width = Math.Max(1, end - bounds.X - inset);
                using (Pen mark = new Pen(text, 1.6F * scale))
                    e.Graphics.DrawLines(mark, new[] { new PointF(end - 4 * scale, Height / 2F - scale), new PointF(end, Height / 2F + 3 * scale), new PointF(end + 4 * scale, Height / 2F - scale) });
            }
            if (Symbol != ButtonSymbol.None)
            {
                int label = TextRenderer.MeasureText(e.Graphics, Text, Font, Size.Empty, TextFormatFlags.NoPadding).Width;
                int icon = (int)Math.Ceiling(16 * scale), gap = (int)Math.Ceiling(6 * scale);
                if (bounds.Width >= label + icon + gap + 2)
                {
                    int start = (Width - label - icon - gap) / 2;
                    GraphicsState state = e.Graphics.Save();
                    e.Graphics.TranslateTransform(start, (Height - icon) / 2F);
                    e.Graphics.ScaleTransform(icon / 16F, icon / 16F);
                    using (Pen pen = new Pen(text, 1.5F) { LineJoin = LineJoin.Round, StartCap = LineCap.Round, EndCap = LineCap.Round })
                    {
                        if (Symbol == ButtonSymbol.Arrow) {
                            e.Graphics.DrawLine(pen, 1.5F, 8, 14, 8);
                            e.Graphics.DrawLines(pen, new[] { new Point(9,3), new Point(14,8), new Point(9,13) });
                        } else if (Symbol == ButtonSymbol.Headset) {
                            using (GraphicsPath headset = ModernGeometry.Rounded(new RectangleF(1,4,14,9), 3)) e.Graphics.DrawPath(pen, headset);
                            e.Graphics.DrawLine(pen, 3, 5, 13, 5);
                            e.Graphics.DrawLines(pen, new[] { new Point(6,12), new Point(8,10), new Point(10,12) });
                        } else {
                            for (int i = 0; i < 3; i++) {
                                int x = i == 1 ? 9 : 4, y = 3 + 5 * i;
                                e.Graphics.DrawLine(pen, 1, y, x - 2, y);
                                e.Graphics.DrawEllipse(pen, x - 1, y - 1.5F, 3, 3);
                                e.Graphics.DrawLine(pen, x + 3, y, 15, y);
                            }
                        }
                    }
                    e.Graphics.Restore(state);
                    bounds.X = start + icon + gap;
                    bounds.Width = Width - bounds.X - 2;
                    align = TextFormatFlags.Left | TextFormatFlags.NoPadding;
                }
            }
            TextRenderer.DrawText(e.Graphics, Text, Font, bounds, text, align | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
            if (Focused && ShowFocusCues && Width > 9 * scale && Height > 9 * scale)
            {
                float inset = 3.5F * scale;
                using (GraphicsPath focus = ModernGeometry.Rounded(new RectangleF(inset, inset, Width - inset * 2, Height - inset * 2), 3 * scale))
                using (Pen line = new Pen(fill.GetBrightness() < .5F ? Color.FromArgb(162,240,213) : Color.FromArgb(18,99,85), 1.4F*scale))
                    e.Graphics.DrawPath(line,focus);
            }
        }
    }
}
