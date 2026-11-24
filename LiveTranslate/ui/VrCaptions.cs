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
            window.OpenDashboardRequested = delegate { OpenVrDashboard(false); };
            window.OpenSettingsRequested = delegate { OpenVrDashboard(true); };
            window.PauseRequested = delegate { ToggleSessionPause(); };
            window.StatusProvider = delegate { return SessionStatusText; };
            window.PausedProvider = delegate { return SessionPaused; };
            window.CanPauseProvider = delegate { return SessionCanPause; };
            window.InputSourceProvider = VrCaptureInput;
            Rectangle area = Screen.FromControl(this).WorkingArea;
            window.Size = new Size(Math.Min(window.Width, area.Width), Math.Min(window.Height, area.Height));
            window.Location = new Point(area.Left + (area.Width - window.Width) / 2, area.Bottom - window.Height);
            window.FormClosed += delegate { if (vrCaptionWindow == window) vrCaptionWindow = null; };
            vrCaptionWindow = window;
            // An ownerless window remains available to the headset window picker when the dashboard is minimized.
            window.Show();
        }

        private void OpenVrDashboard(bool settings)
        {
            if (closing || IsDisposed) return;
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            ShowSessionPage(settings ? "settings" : "live");
            Show();
            Activate();
        }

        private string VrCaptureInput()
        {
            if (SessionPaused) return oneShotPending ? "Reading selected screen area" : "Translation paused";
            if (audioWanted)
            {
                Choice device = devices.SelectedItem as Choice;
                string input = device == null ? "Audio input" : device.Code == "pc" ? "System audio" :
                    device.Code == "both" ? "System audio + microphone" : "Microphone";
                return input + (screenWanted ? " + screen" : "");
            }
            return screenWanted ? "Screen area" : oneShotPending ? "Selected screen area" : screenArmed ? "Screen area armed" : "No capture running";
        }

        private void PresentVrCaption(string kind, string text)
        {
            PresentVrCaption(kind, text, null, null);
        }

        private void PresentVrCaption(string kind, string text, string original, string sourceLabel)
        {
            vrCaptionState.Present(kind, text, original, sourceLabel, VrCaptionWindow.Clock.ElapsedMilliseconds);
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
