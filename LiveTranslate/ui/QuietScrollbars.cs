using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace LiveTranslate
{
    // Paint the existing non-client scrollbar, rather than hiding it or
    // substituting a second scrolling model. Windows still owns its ranges,
    // hit testing, dragging, auto-repeat, wheel, keyboard and accessibility.
    internal sealed class QuietScrollbars : NativeWindow, IDisposable
    {
        private static readonly ConditionalWeakTable<Control, QuietScrollbars> attached = new ConditionalWeakTable<Control, QuietScrollbars>();
        private static readonly ConditionalWeakTable<Control, QuietScrollbars> popups = new ConditionalWeakTable<Control, QuietScrollbars>();
        private readonly Control owner;
        private readonly bool popup;
        private bool painting, disposed;
        private System.Windows.Forms.Timer trackingPaint;

        [StructLayout(LayoutKind.Sequential)]
        private struct NativeRect { internal int Left, Top, Right, Bottom; }
        [StructLayout(LayoutKind.Sequential)]
        private struct NativePoint { internal int X, Y; }
        [StructLayout(LayoutKind.Sequential)]
        private struct ScrollBarInfo
        {
            internal int Size;
            internal NativeRect Rectangle;
            internal int ArrowSize, ThumbTop, ThumbBottom, Reserved;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 6)] internal uint[] States;
        }
        [DllImport("user32.dll")] private static extern bool GetScrollBarInfo(IntPtr window, int id, ref ScrollBarInfo info);
        [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr window, out NativeRect rectangle);
        [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr window, out NativeRect rectangle);
        [DllImport("user32.dll")] private static extern bool ClientToScreen(IntPtr window, ref NativePoint point);
        [DllImport("user32.dll")] private static extern IntPtr GetWindowDC(IntPtr window);
        [DllImport("user32.dll")] private static extern int ReleaseDC(IntPtr window, IntPtr dc);

        internal static void Attach(Control control)
        {
            if (control == null || control.IsDisposed) return;
            attached.GetValue(control, delegate(Control value) { return new QuietScrollbars(value); });
        }

        internal static void AttachPopup(Control control, IntPtr listHandle)
        {
            if (control == null || control.IsDisposed || listHandle == IntPtr.Zero) return;
            QuietScrollbars hook = popups.GetValue(control, delegate(Control value) { return new QuietScrollbars(value, true); });
            if (hook.Handle == listHandle) return;
            if (hook.Handle != IntPtr.Zero) hook.ReleaseHandle();
            hook.AssignHandle(listHandle);
        }

        private QuietScrollbars(Control value) : this(value, false) { }

        private QuietScrollbars(Control value, bool isPopup)
        {
            owner = value;
            popup = isPopup;
            owner.HandleCreated += HandleCreated;
            owner.HandleDestroyed += HandleDestroyed;
            owner.Disposed += OwnerDisposed;
            if (!popup && owner.IsHandleCreated) AssignHandle(owner.Handle);
        }

        private void HandleCreated(object sender, EventArgs e) { if (!disposed && !popup) AssignHandle(owner.Handle); }
        private void HandleDestroyed(object sender, EventArgs e) { if (Handle != IntPtr.Zero) ReleaseHandle(); }
        private void OwnerDisposed(object sender, EventArgs e) { Dispose(); }

        protected override void WndProc(ref Message message)
        {
            bool tracking = message.Msg == 0x00A1 && (message.WParam.ToInt32() == 6 || message.WParam.ToInt32() == 7);
            if (tracking && !WindowTheme.HighContrast)
            {
                // Native scrollbar tracking enters its own message loop and may
                // repaint between WM_VSCROLL callbacks. Repaint only while that
                // native gesture is running; never poll in the background.
                if (trackingPaint == null)
                {
                    trackingPaint = new System.Windows.Forms.Timer { Interval = 40 };
                    trackingPaint.Tick += delegate { if (!disposed && Handle != IntPtr.Zero && !WindowTheme.HighContrast) Paint(IntPtr.Zero); };
                }
                trackingPaint.Start();
            }
            try { base.WndProc(ref message); }
            finally { if (tracking && trackingPaint != null) trackingPaint.Stop(); }
            if (disposed || painting || WindowTheme.HighContrast || Handle == IntPtr.Zero) return;
            switch (message.Msg)
            {
                case 0x000F: // WM_PAINT
                case 0x0085: // WM_NCPAINT
                case 0x0088: // WM_SYNCPAINT
                case 0x0005: // WM_SIZE
                case 0x0047: // WM_WINDOWPOSCHANGED
                case 0x0114: // WM_HSCROLL
                case 0x0115: // WM_VSCROLL
                case 0x020A: // WM_MOUSEWHEEL
                case 0x020E: // WM_MOUSEHWHEEL
                case 0x00A0: // WM_NCMOUSEMOVE
                case 0x00A1: // WM_NCLBUTTONDOWN
                case 0x00A2: // WM_NCLBUTTONUP
                case 0x02A2: // WM_NCMOUSELEAVE
                case 0x0215: // WM_CAPTURECHANGED
                case 0x031A: // WM_THEMECHANGED
                    Paint(IntPtr.Zero);
                    break;
                case 0x0317: // WM_PRINT: draw into the caller's window-origin DC.
                    if ((message.LParam.ToInt64() & 2) != 0) Paint(message.WParam);
                    break;
            }
        }

        private bool Bar(int id, NativeRect window, out Rectangle rectangle, out ScrollBarInfo info)
        {
            info = new ScrollBarInfo { Size = Marshal.SizeOf(typeof(ScrollBarInfo)), States = new uint[6] };
            rectangle = Rectangle.Empty;
            if (!GetScrollBarInfo(Handle, id, ref info) || (info.States[0] & 0x8000) != 0) return false;
            rectangle = Rectangle.FromLTRB(info.Rectangle.Left - window.Left, info.Rectangle.Top - window.Top,
                info.Rectangle.Right - window.Left, info.Rectangle.Bottom - window.Top);
            return rectangle.Width > 1 && rectangle.Height > 1;
        }

        private void Paint(IntPtr target)
        {
            NativeRect window;
            if (!GetWindowRect(Handle, out window)) return;
            Rectangle vertical, horizontal;
            ScrollBarInfo verticalInfo, horizontalInfo;
            bool v = Bar(-5, window, out vertical, out verticalInfo), h = Bar(-6, window, out horizontal, out horizontalInfo);
            if (!v && !h && !popup) return;
            bool release = target == IntPtr.Zero;
            IntPtr dc = release ? GetWindowDC(Handle) : target;
            if (dc == IntPtr.Zero) return;
            painting = true;
            try
            {
                using (Graphics graphics = Graphics.FromHdc(dc))
                {
                    graphics.SmoothingMode = SmoothingMode.AntiAlias;
                    if (v) DrawBar(graphics, vertical, verticalInfo, true);
                    if (h) DrawBar(graphics, horizontal, horizontalInfo, false);
                    if (v && h)
                        using (Brush fill = new SolidBrush(WindowTheme.Field))
                            graphics.FillRectangle(fill, new Rectangle(vertical.Left, horizontal.Top, vertical.Width, horizontal.Height));
                    if (popup) DrawPopupFrame(graphics, window, v ? vertical.Width : 0, h ? horizontal.Height : 0);
                }
            }
            finally { painting = false; if (release) ReleaseDC(Handle, dc); }
        }

        private void DrawPopupFrame(Graphics graphics, NativeRect window, int verticalWidth, int horizontalHeight)
        {
            NativeRect client;
            NativePoint origin = new NativePoint();
            if (!GetClientRect(Handle, out client) || !ClientToScreen(Handle, ref origin)) return;
            int width = window.Right - window.Left, height = window.Bottom - window.Top;
            int left = Math.Max(0, Math.Min(4, origin.X - window.Left));
            int top = Math.Max(0, Math.Min(4, origin.Y - window.Top));
            int right = Math.Max(0, Math.Min(4, width - left - client.Right - verticalWidth));
            int bottom = Math.Max(0, Math.Min(4, height - top - client.Bottom - horizontalHeight));
            using (Brush edge = new SolidBrush(WindowTheme.Border))
            {
                graphics.FillRectangle(edge, 0, 0, width, top);
                graphics.FillRectangle(edge, 0, 0, left, height);
                graphics.FillRectangle(edge, width - right, 0, right, height);
                graphics.FillRectangle(edge, 0, height - bottom, width, bottom);
            }
        }

        private static void DrawBar(Graphics graphics, Rectangle bar, ScrollBarInfo info, bool vertical)
        {
            using (Brush track = new SolidBrush(WindowTheme.Field)) graphics.FillRectangle(track, bar);
            int arrow = Math.Max(1, Math.Min(info.ArrowSize, (vertical ? bar.Height : bar.Width) / 2));
            Rectangle first = vertical ? new Rectangle(bar.Left, bar.Top, bar.Width, arrow) : new Rectangle(bar.Left, bar.Top, arrow, bar.Height);
            Rectangle last = vertical ? new Rectangle(bar.Left, bar.Bottom - arrow, bar.Width, arrow) : new Rectangle(bar.Right - arrow, bar.Top, arrow, bar.Height);
            DrawArrow(graphics, first, vertical, false, (info.States[1] & 1) == 0);
            DrawArrow(graphics, last, vertical, true, (info.States[5] & 1) == 0);
            int start = Math.Max(arrow, info.ThumbTop), end = Math.Min((vertical ? bar.Height : bar.Width) - arrow, info.ThumbBottom);
            if (end <= start) return;
            Rectangle thumb = vertical ? new Rectangle(bar.Left + 3, bar.Top + start, Math.Max(1, bar.Width - 6), end - start) :
                new Rectangle(bar.Left + start, bar.Top + 3, end - start, Math.Max(1, bar.Height - 6));
            Color color = (info.States[3] & (0x8 | 0x80)) != 0 ? Color.FromArgb(91, 109, 133) : Color.FromArgb(53, 67, 87);
            float radius = Math.Min(4F, Math.Min(thumb.Width, thumb.Height) / 2F);
            using (GraphicsPath path = ModernGeometry.Rounded(thumb, radius))
            using (Brush fill = new SolidBrush(color)) graphics.FillPath(fill, path);
        }

        private static void DrawArrow(Graphics graphics, Rectangle bounds, bool vertical, bool forward, bool enabled)
        {
            float x = bounds.Left + bounds.Width / 2F, y = bounds.Top + bounds.Height / 2F;
            float sign = forward ? 1F : -1F;
            using (Pen pen = new Pen(enabled ? WindowTheme.Muted : WindowTheme.Disabled, 1.3F))
            {
                pen.StartCap = pen.EndCap = LineCap.Round;
                PointF[] points = vertical ? new[] { new PointF(x - 3, y - sign), new PointF(x, y + 2 * sign), new PointF(x + 3, y - sign) } :
                    new[] { new PointF(x - sign, y - 3), new PointF(x + 2 * sign, y), new PointF(x - sign, y + 3) };
                graphics.DrawLines(pen, points);
            }
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            if (trackingPaint != null) { trackingPaint.Stop(); trackingPaint.Dispose(); trackingPaint = null; }
            owner.HandleCreated -= HandleCreated;
            owner.HandleDestroyed -= HandleDestroyed;
            owner.Disposed -= OwnerDisposed;
            if (Handle != IntPtr.Zero) ReleaseHandle();
            if (popup) popups.Remove(owner); else attached.Remove(owner);
        }
    }
}
