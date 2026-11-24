using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Runtime.CompilerServices;
using System.Windows.Forms;

namespace LiveTranslate
{
    // Colors belong to this application. Windows theme preferences are never changed.
    internal static class WindowTheme
    {
        private static readonly ConditionalWeakTable<Control, object> watchedControls = new ConditionalWeakTable<Control, object>();
        internal static bool HighContrast { get { return SystemInformation.HighContrast; } }
        internal static Color Background { get { return HighContrast ? SystemColors.Window : Color.FromArgb(9, 14, 22); } }
        internal static Color Card { get { return HighContrast ? SystemColors.Window : Color.FromArgb(20, 27, 38); } }
        internal static Color Field { get { return HighContrast ? SystemColors.Window : Color.FromArgb(14, 21, 32); } }
        internal static Color Border { get { return HighContrast ? SystemColors.WindowText : Color.FromArgb(40, 52, 70); } }
        internal static Color Ink { get { return HighContrast ? SystemColors.WindowText : Color.FromArgb(245, 247, 251); } }
        internal static Color Muted { get { return HighContrast ? SystemColors.WindowText : Color.FromArgb(157, 171, 191); } }
        internal static Color Accent { get { return HighContrast ? SystemColors.Highlight : Color.FromArgb(54, 224, 190); } }
        internal static Color AccentInk { get { return HighContrast ? SystemColors.HighlightText : Color.FromArgb(9, 30, 29); } }
        internal static Color Purple { get { return HighContrast ? SystemColors.Highlight : Color.FromArgb(187, 173, 255); } }
        internal static Color Warning { get { return HighContrast ? SystemColors.WindowText : Color.FromArgb(234, 189, 120); } }
        internal static Color Disabled { get { return HighContrast ? SystemColors.GrayText : Color.FromArgb(115, 129, 150); } }

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int length);
        [DllImport("uxtheme.dll", CharSet = CharSet.Unicode)]
        private static extern int SetWindowTheme(IntPtr window, string application, string subId);

        internal static Color Surround(Control control)
        {
            if (HighContrast) return SystemColors.Window;
            for (Control owner = control == null ? null : control.Parent; owner != null; owner = owner.Parent)
            {
                ModernCard card = owner as ModernCard;
                if (card != null && card.FillColor.A == 255) return card.FillColor;
                if (owner.BackColor.A == 255) return owner.BackColor;
            }
            return Card;
        }

        internal static void Apply(Form window)
        {
            if (window == null) return;
            window.HandleCreated += delegate { ApplyFrame(window); };
            window.SystemColorsChanged += delegate { ApplyFrame(window); };
            WatchControls(window);
            if (window.IsHandleCreated) ApplyFrame(window);
        }

        private static void WatchControls(Control parent)
        {
            object watched;
            if (watchedControls.TryGetValue(parent, out watched)) return;
            watchedControls.Add(parent, new object());
            AttachScrollbars(parent);
            parent.ControlAdded += delegate(object sender, ControlEventArgs e) { WatchControls(e.Control); };
            foreach (Control child in parent.Controls) WatchControls(child);
        }

        private static void AttachScrollbars(Control control)
        {
            ScrollableControl scrolling = control as ScrollableControl;
            if (control is TextBoxBase || control is ListView || (scrolling != null && scrolling.AutoScroll))
                QuietScrollbars.Attach(control);
        }

        private static void ApplyFrame(Form window)
        {
            if (window.IsDisposed || !window.IsHandleCreated) return;
            try
            {
                int dark = HighContrast ? 0 : 1;
                // Older supported Windows versions use attribute 19 instead of 20.
                if (DwmSetWindowAttribute(window.Handle, 20, ref dark, sizeof(int)) != 0)
                    DwmSetWindowAttribute(window.Handle, 19, ref dark, sizeof(int));
            }
            catch (DllNotFoundException) { }
            catch (EntryPointNotFoundException) { }
        }

        // Optional native scrollbar/dropdown theme, scoped to the supplied control.
        // Call after creation; repeat after a control recreates its HWND.
        internal static void ApplyControl(Control control)
        {
            if (control == null || control.IsDisposed || !control.IsHandleCreated) return;
            AttachScrollbars(control);
            try { SetWindowTheme(control.Handle, HighContrast ? null : control is ComboBox ? "DarkMode_CFD" : "DarkMode_Explorer", null); }
            catch (DllNotFoundException) { }
            catch (EntryPointNotFoundException) { }
        }
    }
}
