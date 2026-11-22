using System;
using System.Drawing;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed partial class MainForm
    {
        readonly VrCaptionState vrCaptionState = new VrCaptionState();
        VrCaptionWindow vrCaptionWindow;

        private void OpenVrCaptions()
        {
            if (vrCaptionWindow != null && !vrCaptionWindow.IsDisposed)
            {
                if (vrCaptionWindow.WindowState == FormWindowState.Minimized) vrCaptionWindow.WindowState = FormWindowState.Normal;
                vrCaptionWindow.Show();
                vrCaptionWindow.Activate();
                return;
            }
            var window = new VrCaptionWindow(vrCaptionState);
            Rectangle area = Screen.FromControl(this).WorkingArea;
            window.Size = new Size(Math.Min(window.Width, area.Width), Math.Min(window.Height, area.Height));
            window.Location = new Point(area.Left + (area.Width - window.Width) / 2, area.Bottom - window.Height);
            window.FormClosed += delegate { if (vrCaptionWindow == window) vrCaptionWindow = null; };
            vrCaptionWindow = window;
            // An ownerless window remains available to the headset window picker when the dashboard is minimized.
            window.Show();
        }

        private void PresentVrCaption(string kind, string text)
        {
            vrCaptionState.Present(kind, text, VrCaptionWindow.Clock.ElapsedMilliseconds);
            if (vrCaptionWindow != null) vrCaptionWindow.RefreshCaptions();
        }

        private void ClearVrCaption(string kind)
        {
            vrCaptionState.Clear(kind);
            if (vrCaptionWindow != null) vrCaptionWindow.RefreshCaptions();
        }

        private long VrCaptionHandle()
        {
            return vrCaptionWindow != null && vrCaptionWindow.IsHandleCreated ? vrCaptionWindow.Handle.ToInt64() : 0;
        }

        private void CloseVrCaptions()
        {
            vrCaptionState.Clear(null);
            if (vrCaptionWindow != null) vrCaptionWindow.Close();
        }
    }
}
