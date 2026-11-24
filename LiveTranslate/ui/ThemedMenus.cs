using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace LiveTranslate
{
    // This renderer belongs only to the supplied menu. It never changes the
    // ToolStripManager renderer or a Windows theme preference.
    internal static class MenuTheme
    {
        internal static void Apply(ContextMenuStrip menu)
        {
            if (menu == null || menu.IsDisposed) return;
            if (WindowTheme.HighContrast)
            {
                menu.BackColor = SystemColors.Menu;
                menu.ForeColor = SystemColors.MenuText;
                if (!(menu.Renderer is ToolStripSystemRenderer)) menu.Renderer = new ToolStripSystemRenderer();
            }
            else
            {
                menu.BackColor = WindowTheme.Card;
                menu.ForeColor = WindowTheme.Ink;
                if (!(menu.Renderer is QuietMenuRenderer)) menu.Renderer = new QuietMenuRenderer();
            }
        }

        private sealed class QuietMenuColors : ProfessionalColorTable
        {
            internal QuietMenuColors() { UseSystemColors = false; }
            private static Color Selected { get { return Color.FromArgb(28, 48, 57); } }
            public override Color ToolStripDropDownBackground { get { return WindowTheme.Card; } }
            public override Color MenuBorder { get { return WindowTheme.Border; } }
            public override Color MenuItemBorder { get { return WindowTheme.Border; } }
            public override Color MenuItemSelected { get { return Selected; } }
            public override Color MenuItemSelectedGradientBegin { get { return Selected; } }
            public override Color MenuItemSelectedGradientEnd { get { return Selected; } }
            public override Color MenuItemPressedGradientBegin { get { return Selected; } }
            public override Color MenuItemPressedGradientMiddle { get { return Selected; } }
            public override Color MenuItemPressedGradientEnd { get { return Selected; } }
            public override Color ImageMarginGradientBegin { get { return WindowTheme.Field; } }
            public override Color ImageMarginGradientMiddle { get { return WindowTheme.Field; } }
            public override Color ImageMarginGradientEnd { get { return WindowTheme.Field; } }
            public override Color CheckBackground { get { return WindowTheme.Field; } }
            public override Color CheckSelectedBackground { get { return Selected; } }
            public override Color CheckPressedBackground { get { return Selected; } }
            public override Color SeparatorDark { get { return WindowTheme.Border; } }
            public override Color SeparatorLight { get { return WindowTheme.Border; } }
        }

        private sealed class QuietMenuRenderer : ToolStripProfessionalRenderer
        {
            internal QuietMenuRenderer() : base(new QuietMenuColors()) { RoundedEdges = false; }

            protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
            {
                e.TextColor = e.Item.Enabled ? WindowTheme.Ink : WindowTheme.Disabled;
                base.OnRenderItemText(e);
            }

            protected override void OnRenderArrow(ToolStripArrowRenderEventArgs e)
            {
                e.ArrowColor = e.Item.Enabled ? WindowTheme.Muted : WindowTheme.Disabled;
                base.OnRenderArrow(e);
            }

            protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e)
            {
                ToolStripMenuItem item = e.Item as ToolStripMenuItem;
                if (item == null) { base.OnRenderItemCheck(e); return; }
                Rectangle bounds = e.ImageRectangle;
                float scale = Math.Max(.5F, Math.Min(bounds.Width, bounds.Height) / 16F);
                float x = bounds.Left + bounds.Width / 2F, y = bounds.Top + bounds.Height / 2F;
                Color color = item.Enabled ? WindowTheme.Accent : WindowTheme.Disabled;
                GraphicsState state = e.Graphics.Save();
                try
                {
                    e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
                    using (Pen pen = new Pen(color, 1.8F * scale) { StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round })
                    {
                        if (item.CheckState == CheckState.Indeterminate)
                            e.Graphics.DrawLine(pen, x - 4 * scale, y, x + 4 * scale, y);
                        else
                            e.Graphics.DrawLines(pen, new[] { new PointF(x - 4.5F * scale, y),
                                new PointF(x - 1.2F * scale, y + 3.3F * scale), new PointF(x + 5F * scale, y - 3.4F * scale) });
                    }
                }
                finally { e.Graphics.Restore(state); }
            }
        }
    }
}
