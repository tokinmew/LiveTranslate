using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class OpacitySlider : Control
    {
        int value = 95;
        internal event EventHandler ValueChanged;
        internal OpacitySlider()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                ControlStyles.ResizeRedraw | ControlStyles.Selectable, true);
            Size = new Size(230, 32); MinimumSize = new Size(80, 26); TabStop = true; Cursor = Cursors.Hand;
            BackColor = WindowTheme.Field; ForeColor = WindowTheme.Accent;
            AccessibleName = "VR background opacity"; AccessibleRole = AccessibleRole.Slider;
        }
        internal int Value
        {
            get { return value; }
            set
            {
                int next = Math.Max(0, Math.Min(100, value));
                if (this.value == next) return;
                this.value = next; Invalidate(); AccessibilityNotifyClients(AccessibleEvents.ValueChange, -1);
                if (ValueChanged != null) ValueChanged(this, EventArgs.Empty);
            }
        }
        void SetAt(int x) { Value = (int)Math.Round((x - 12) * 100.0 / Math.Max(1, Width - 24)); }
        protected override void OnMouseDown(MouseEventArgs e)
        { base.OnMouseDown(e); if (Enabled && e.Button == MouseButtons.Left) { Focus(); Capture = true; SetAt(e.X); } }
        protected override void OnMouseMove(MouseEventArgs e) { base.OnMouseMove(e); if (Capture && Enabled) SetAt(e.X); }
        protected override void OnMouseUp(MouseEventArgs e) { base.OnMouseUp(e); if (e.Button == MouseButtons.Left) Capture = false; }
        protected override bool IsInputKey(Keys keyData)
        {
            Keys key = keyData & Keys.KeyCode;
            return key == Keys.Left || key == Keys.Right || key == Keys.Up || key == Keys.Down || key == Keys.Home ||
                key == Keys.End || key == Keys.PageUp || key == Keys.PageDown || base.IsInputKey(keyData);
        }
        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (Enabled)
            {
                if (e.KeyCode == Keys.Left || e.KeyCode == Keys.Down) Value--;
                else if (e.KeyCode == Keys.Right || e.KeyCode == Keys.Up) Value++;
                else if (e.KeyCode == Keys.PageUp) Value += 10;
                else if (e.KeyCode == Keys.PageDown) Value -= 10;
                else if (e.KeyCode == Keys.Home) Value = 0;
                else if (e.KeyCode == Keys.End) Value = 100;
                else { base.OnKeyDown(e); return; }
                e.Handled = e.SuppressKeyPress = true;
            }
            base.OnKeyDown(e);
        }
        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(WindowTheme.HighContrast ? SystemColors.Window : BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            int y = Height / 2, x = 12 + (Width - 24) * Value / 100;
            using (var track = new Pen(WindowTheme.HighContrast ? SystemColors.WindowText : WindowTheme.Border, 5))
            using (var active = new Pen(WindowTheme.HighContrast ? SystemColors.Highlight : ForeColor, 5))
            using (var thumb = new SolidBrush(!Enabled ? WindowTheme.Disabled : WindowTheme.HighContrast ? SystemColors.WindowText : WindowTheme.Ink))
            {
                track.StartCap = track.EndCap = active.StartCap = active.EndCap = LineCap.Round;
                e.Graphics.DrawLine(track, 12, y, Math.Max(12, Width - 12), y);
                if (Value > 0) e.Graphics.DrawLine(active, 12, y, x, y);
                e.Graphics.FillEllipse(thumb, x - 7, y - 7, 14, 14);
            }
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -2, -2));
        }
        protected override AccessibleObject CreateAccessibilityInstance() { return new SliderAccessibleObject(this); }
        sealed class SliderAccessibleObject : ControlAccessibleObject
        {
            readonly OpacitySlider owner;
            internal SliderAccessibleObject(OpacitySlider owner) : base(owner) { this.owner = owner; }
            public override AccessibleRole Role { get { return AccessibleRole.Slider; } }
            public override string Value
            {
                get { return owner.Value.ToString(CultureInfo.InvariantCulture) + "%"; }
                set { int parsed; if (owner.Enabled && Int32.TryParse((value ?? "").TrimEnd('%'), out parsed)) owner.Value = parsed; }
            }
        }
    }
}
