using System;
using System.Drawing;
using System.Windows.Forms;

namespace LiveTranslate
{
    // Keep the native tab/page and keyboard contracts. Only the surrounding
    // chrome is painted here, including the otherwise white native page frame.
    internal sealed class ThemedTabControl : TabControl
    {
        internal ThemedTabControl()
        {
            ConfigurePainting();
            BackColor = WindowTheme.Background;
            ForeColor = WindowTheme.Ink;
            ResizeRedraw = true;
        }

        private void ConfigurePainting()
        {
            bool custom = !WindowTheme.HighContrast;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                ControlStyles.OptimizedDoubleBuffer, custom);
            DrawMode = custom ? TabDrawMode.OwnerDrawFixed : TabDrawMode.Normal;
        }

        protected override void OnSystemColorsChanged(EventArgs e)
        {
            base.OnSystemColorsChanged(e);
            ConfigurePainting();
            UpdateStyles();
            Invalidate();
        }

        protected override void OnSelectedIndexChanged(EventArgs e)
        {
            base.OnSelectedIndexChanged(e);
            Invalidate();
        }

        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
        protected override void OnEnabledChanged(EventArgs e) { base.OnEnabledChanged(e); Invalidate(); }

        protected override bool ProcessCmdKey(ref Message message, Keys keyData)
        {
            // Retain page switching when focus is inside a page, even though
            // the native header's pixels are supplied by this control.
            if (Enabled && TabCount > 1 && (keyData == (Keys.Control | Keys.Tab) ||
                keyData == (Keys.Control | Keys.Shift | Keys.Tab)))
            {
                int direction = (keyData & Keys.Shift) != 0 ? -1 : 1;
                SelectedIndex = (Math.Max(0, SelectedIndex) + direction + TabCount) % TabCount;
                return true;
            }
            return base.ProcessCmdKey(ref message, keyData);
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            if (WindowTheme.HighContrast) base.OnPaintBackground(e);
            else e.Graphics.Clear(WindowTheme.Background);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            if (WindowTheme.HighContrast) { base.OnPaint(e); return; }
            e.Graphics.Clear(WindowTheme.Background);
            Rectangle page = DisplayRectangle;
            Rectangle frame = Rectangle.Inflate(page, 3, 3);
            frame.Intersect(ClientRectangle);
            if (frame.Width > 1 && frame.Height > 1)
            {
                using (Brush fill = new SolidBrush(WindowTheme.Card)) e.Graphics.FillRectangle(fill, frame);
                using (Pen outline = new Pen(WindowTheme.Border))
                    e.Graphics.DrawRectangle(outline, frame.Left, frame.Top, frame.Width - 1, frame.Height - 1);
            }
            for (int index = 0; index < TabCount; index++)
            {
                Rectangle tab = GetTabRect(index);
                bool selected = index == SelectedIndex;
                Rectangle face = tab;
                if (selected) face.Height += 2;
                using (Brush fill = new SolidBrush(selected ? WindowTheme.Card : WindowTheme.Background))
                    e.Graphics.FillRectangle(fill, face);
                Rectangle text = Rectangle.Inflate(tab, -7, -2);
                TextRenderer.DrawText(e.Graphics, TabPages[index].Text, Font, text,
                    Enabled ? selected ? WindowTheme.Ink : WindowTheme.Muted : WindowTheme.Disabled,
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                    TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
                if (selected)
                {
                    using (Pen line = new Pen(WindowTheme.Accent, 2F))
                        e.Graphics.DrawLine(line, tab.Left + 9, tab.Bottom - 2, tab.Right - 9, tab.Bottom - 2);
                    if (Focused && ShowFocusCues)
                        ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(tab, -4, -4), WindowTheme.Muted, WindowTheme.Card);
                }
            }
        }
    }
}
