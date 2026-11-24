using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace LiveTranslate
{
    // Native controls still own selection, keyboard input, accessibility and repeat
    // clicks. Only their chrome is painted here; no Windows preference is changed.
    internal sealed class ThemedComboBox : ComboBox
    {
        [StructLayout(LayoutKind.Sequential)] private struct NativeRect { public int Left, Top, Right, Bottom; }
        [StructLayout(LayoutKind.Sequential)] private struct ComboInfo
        {
            public int Size; public NativeRect Item, Button; public int ButtonState;
            public IntPtr Combo, Edit, List;
        }
        [DllImport("user32.dll")] private static extern bool GetComboBoxInfo(IntPtr window, ref ComboInfo info);
        public ThemedComboBox()
        {
            DropDownStyle = ComboBoxStyle.DropDownList;
            DrawMode = DrawMode.OwnerDrawFixed;
            FlatStyle = FlatStyle.Flat;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            BackColor = WindowTheme.Field;
            ForeColor = WindowTheme.Ink;
            UpdateItemHeight();
        }

        private void UpdateItemHeight() { ItemHeight = Math.Max(20, Font.Height + 4); }
        protected override void OnFontChanged(EventArgs e) { base.OnFontChanged(e); UpdateItemHeight(); }
        protected override void OnSelectedIndexChanged(EventArgs e) { base.OnSelectedIndexChanged(e); Invalidate(); }
        protected override void OnDropDown(EventArgs e)
        {
            base.OnDropDown(e);
            ComboInfo info = new ComboInfo(); info.Size = Marshal.SizeOf(typeof(ComboInfo));
            if (IsHandleCreated && GetComboBoxInfo(Handle, ref info) && info.List != IntPtr.Zero)
                QuietScrollbars.AttachPopup(this, info.List);
            Invalidate();
        }
        protected override void OnDropDownClosed(EventArgs e) { base.OnDropDownClosed(e); Invalidate(); }
        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Invalidate(); }
        protected override void OnSystemColorsChanged(EventArgs e)
        {
            base.OnSystemColorsChanged(e);
            BackColor = WindowTheme.Field;
            ForeColor = WindowTheme.Ink;
            Invalidate();
        }

        protected override void OnDrawItem(DrawItemEventArgs e)
        {
            bool selected = (e.State & DrawItemState.Selected) != 0;
            Color fill = WindowTheme.HighContrast ? (selected ? SystemColors.Highlight : SystemColors.Window) :
                selected ? Color.FromArgb(30, 62, 65) : WindowTheme.Field;
            Color color = WindowTheme.HighContrast ? (selected ? SystemColors.HighlightText : SystemColors.WindowText) :
                Enabled ? WindowTheme.Ink : WindowTheme.Disabled;
            using (var brush = new SolidBrush(fill)) e.Graphics.FillRectangle(brush, e.Bounds);
            if (e.Index >= 0 && e.Index < Items.Count)
                TextRenderer.DrawText(e.Graphics, GetItemText(Items[e.Index]), Font,
                    Rectangle.Inflate(e.Bounds, -7, 0), color, TextFormatFlags.Left | TextFormatFlags.VerticalCenter |
                    TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix);
            if (WindowTheme.HighContrast) e.DrawFocusRectangle();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            if (Width < 2 || Height < 2) return;
            Color fill = WindowTheme.HighContrast ? SystemColors.Window : WindowTheme.Field;
            Color color = Enabled ? WindowTheme.Ink : WindowTheme.HighContrast ? SystemColors.GrayText : WindowTheme.Disabled;
            Color edge = Focused || DroppedDown ? WindowTheme.Accent : WindowTheme.Border;
            e.Graphics.Clear(fill);
            using (var line = new Pen(edge)) e.Graphics.DrawRectangle(line, 0, 0, Width - 1, Height - 1);
            Rectangle text = new Rectangle(8, 1, Math.Max(1, Width - 33), Height - 2);
            TextRenderer.DrawText(e.Graphics, SelectedIndex >= 0 ? GetItemText(SelectedItem) : Text, Font, text,
                color, TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis |
                TextFormatFlags.SingleLine | TextFormatFlags.NoPrefix);
            float x = Width - 14F, y = Height / 2F;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var arrow = new Pen(color, 1.25F))
                e.Graphics.DrawLines(arrow, new[] { new PointF(x - 3F, y - 1.5F), new PointF(x, y + 1.5F), new PointF(x + 3F, y - 1.5F) });
            if (WindowTheme.HighContrast && Focused && ShowFocusCues)
                ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -3, -3));
        }
    }

    internal sealed class ThemedTextBox : TextBox
    {
        public ThemedTextBox() { BorderStyle = BorderStyle.FixedSingle; }
        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if (BorderStyle != BorderStyle.None && (m.Msg == 0x85 || m.Msg == 0xF || m.Msg == 0x14 || m.Msg == 0x7 || m.Msg == 0x8))
                QuietInputFrame.Paint(this);
            if (BorderStyle != BorderStyle.None && m.Msg == 0x317 && m.WParam != IntPtr.Zero)
                QuietInputFrame.Paint(this, m.WParam);
        }
        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); QuietInputFrame.Redraw(this); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); QuietInputFrame.Redraw(this); }
        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); QuietInputFrame.Redraw(this); }
    }

    internal sealed class ThemedNumericUpDown : NumericUpDown
    {
        private readonly Dictionary<Control, SpinnerChrome> spinners = new Dictionary<Control, SpinnerChrome>();
        public ThemedNumericUpDown()
        {
            BorderStyle = BorderStyle.FixedSingle;
            BackColor = WindowTheme.Field;
            ForeColor = WindowTheme.Ink;
        }
        protected override void OnCreateControl() { base.OnCreateControl(); AttachSpinners(); }
        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); AttachSpinners(); }
        private void AttachSpinners()
        {
            // UpDownBase exposes its native edit and repeat-button controls through
            // Controls. Only the button's paint messages are subclassed.
            foreach (Control child in Controls)
                if (child.GetType().Name == "UpDownButtons" && !spinners.ContainsKey(child))
                    spinners.Add(child, new SpinnerChrome(this, child));
        }
        protected override void WndProc(ref Message m)
        {
            base.WndProc(ref m);
            if (BorderStyle != BorderStyle.None && (m.Msg == 0x85 || m.Msg == 0xF || m.Msg == 0x14 || m.Msg == 0x7 || m.Msg == 0x8))
                QuietInputFrame.Paint(this);
            if (BorderStyle != BorderStyle.None && m.Msg == 0x317 && m.WParam != IntPtr.Zero)
                QuietInputFrame.Paint(this, m.WParam);
        }
        protected override void OnEnter(EventArgs e) { base.OnEnter(e); QuietInputFrame.Redraw(this); }
        protected override void OnLeave(EventArgs e) { base.OnLeave(e); QuietInputFrame.Redraw(this); }
        protected override void OnEnabledChanged(EventArgs e)
        {
            base.OnEnabledChanged(e);
            QuietInputFrame.Redraw(this);
            foreach (Control child in Controls) child.Invalidate();
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                foreach (SpinnerChrome spinner in spinners.Values) spinner.Dispose();
                spinners.Clear();
            }
            base.Dispose(disposing);
        }

        private sealed class SpinnerChrome : NativeWindow, IDisposable
        {
            private readonly ThemedNumericUpDown owner;
            private readonly Control button;
            private int pressed;
            internal SpinnerChrome(ThemedNumericUpDown value, Control child)
            {
                owner = value; button = child;
                button.HandleCreated += HandleCreated;
                button.HandleDestroyed += HandleDestroyed;
                if (button.IsHandleCreated) AssignHandle(button.Handle);
            }
            private void HandleCreated(object sender, EventArgs e) { AssignHandle(button.Handle); }
            private void HandleDestroyed(object sender, EventArgs e) { if (Handle != IntPtr.Zero) ReleaseHandle(); }
            protected override void WndProc(ref Message m)
            {
                if (m.Msg == 0x201) pressed = ((m.LParam.ToInt64() >> 16) & 65535) < button.Height / 2 ? 1 : 2;
                if (m.Msg == 0x202 || m.Msg == 0x215) pressed = 0;
                base.WndProc(ref m);
                if (m.Msg == 0xF || m.Msg == 0x14 || m.Msg == 0x201 || m.Msg == 0x202 || m.Msg == 0x215)
                {
                    if (!WindowTheme.HighContrast && Handle != IntPtr.Zero)
                        using (Graphics graphics = Graphics.FromHwnd(Handle)) Paint(graphics);
                }
                else if ((m.Msg == 0x317 || m.Msg == 0x318) && m.WParam != IntPtr.Zero && !WindowTheme.HighContrast)
                    using (Graphics graphics = Graphics.FromHdc(m.WParam)) Paint(graphics);
            }
            private void Paint(Graphics graphics)
            {
                Rectangle bounds = button.ClientRectangle;
                if (bounds.Width < 2 || bounds.Height < 4) return;
                graphics.Clear(WindowTheme.Field);
                int half = bounds.Height / 2;
                if (pressed != 0 && owner.Enabled)
                    using (var shade = new SolidBrush(Color.FromArgb(29, 43, 57)))
                        graphics.FillRectangle(shade, 0, pressed == 1 ? 0 : half, bounds.Width, half + 1);
                using (var edge = new Pen(WindowTheme.Border))
                {
                    graphics.DrawLine(edge, 0, 0, 0, bounds.Height);
                    graphics.DrawLine(edge, 0, half, bounds.Width, half);
                }
                Color color = owner.Enabled ? WindowTheme.Muted : WindowTheme.Disabled;
                float x = bounds.Width / 2F;
                using (var arrow = new Pen(color, 1.1F))
                {
                    graphics.DrawLines(arrow, new[] { new PointF(x - 2.5F, half / 2F + 1), new PointF(x, half / 2F - 1.5F), new PointF(x + 2.5F, half / 2F + 1) });
                    graphics.DrawLines(arrow, new[] { new PointF(x - 2.5F, half + half / 2F - 1), new PointF(x, half + half / 2F + 1.5F), new PointF(x + 2.5F, half + half / 2F - 1) });
                }
            }
            public void Dispose()
            {
                button.HandleCreated -= HandleCreated;
                button.HandleDestroyed -= HandleDestroyed;
                if (Handle != IntPtr.Zero) ReleaseHandle();
            }
        }
    }

    internal static class QuietInputFrame
    {
        [StructLayout(LayoutKind.Sequential)] private struct NativeRect { public int Left, Top, Right, Bottom; }
        [DllImport("user32.dll")] private static extern IntPtr GetWindowDC(IntPtr window);
        [DllImport("user32.dll")] private static extern int ReleaseDC(IntPtr window, IntPtr dc);
        [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr window, out NativeRect bounds);
        [DllImport("user32.dll")] private static extern bool RedrawWindow(IntPtr window, IntPtr update, IntPtr region, uint flags);

        internal static void Redraw(Control control)
        {
            if (control.IsHandleCreated && !control.IsDisposed) RedrawWindow(control.Handle, IntPtr.Zero, IntPtr.Zero, 0x401);
        }
        internal static void Paint(Control control)
        {
            if (WindowTheme.HighContrast || !control.IsHandleCreated || control.IsDisposed) return;
            IntPtr dc = GetWindowDC(control.Handle);
            if (dc == IntPtr.Zero) return;
            try { Paint(control, dc); }
            finally { ReleaseDC(control.Handle, dc); }
        }
        internal static void Paint(Control control, IntPtr dc)
        {
            if (WindowTheme.HighContrast || dc == IntPtr.Zero) return;
            NativeRect native;
            if (!GetWindowRect(control.Handle, out native)) return;
            int width = native.Right - native.Left, height = native.Bottom - native.Top;
            if (width < 3 || height < 3) return;
            Color color = control.ContainsFocus ? WindowTheme.Accent : WindowTheme.Border;
            using (Graphics graphics = Graphics.FromHdc(dc))
            using (var line = new Pen(color)) graphics.DrawRectangle(line, 0, 0, width - 1, height - 1);
        }
    }
}
