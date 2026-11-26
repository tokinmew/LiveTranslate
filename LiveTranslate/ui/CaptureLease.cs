using System;
using System.Collections.Generic;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed partial class MainForm
    {
        private const int BeginScreenSample = 0x8000 + 0x241;
        private const int EndScreenSample = BeginScreenSample + 1;
        private const int BeginManualScreenSample = BeginScreenSample + 2;
        private const string CaptureCoordinator = "LiveTranslate.ScreenSample.v1";
        private const string ManualSampleHidden = "LiveTranslate.ManualSampleHidden.v1";
        private int sampleToken;
        private Timer sampleTimeout;
        private readonly List<KeyValuePair<Form, double>> manualSampleWindows = new List<KeyValuePair<Form, double>>();

        [DllImport("user32.dll", EntryPoint = "SetPropW", CharSet = CharSet.Unicode)]
        private static extern bool SetSampleProperty(IntPtr window, string key, IntPtr value);
        [DllImport("user32.dll", EntryPoint = "RemovePropW", CharSet = CharSet.Unicode)]
        private static extern IntPtr RemoveSampleProperty(IntPtr window, string key);
        [DllImport("dwmapi.dll")]
        private static extern int DwmFlush();

        protected override void OnHandleCreated(EventArgs args)
        {
            base.OnHandleCreated(args);
            SetSampleProperty(Handle, CaptureCoordinator, new IntPtr(1));
        }

        protected override void OnHandleDestroyed(EventArgs args)
        {
            RemoveSampleProperty(Handle, CaptureCoordinator);
            ReleaseScreenSample();
            if (sampleTimeout != null)
            {
                sampleTimeout.Dispose();
                sampleTimeout = null;
            }
            base.OnHandleDestroyed(args);
        }

        private void ReleaseScreenSample()
        {
            if (sampleTimeout != null) sampleTimeout.Stop();
            if (sampleToken == 0) return;
            sampleToken = 0;
            foreach (KeyValuePair<Form, double> saved in manualSampleWindows)
            {
                Form window = saved.Key;
                if (window.IsDisposed) continue;
                if (window.IsHandleCreated) RemoveSampleProperty(window.Handle, ManualSampleHidden);
                // Opacity does not alter visibility, focus, window placement or
                // minimized state, unlike hiding and showing a dashboard.
                if (!closing) window.Opacity = saved.Value;
            }
            manualSampleWindows.Clear();
            if (!closing && screenCaptions != null) screenCaptions.EndCapturePause();
        }

        private void PrepareManualScreenSample()
        {
            if (captureApplication != null) return;
            Rectangle target = CaptureBounds();
            var windows = new List<Form>();
            foreach (Form window in Application.OpenForms) windows.Add(window);
            foreach (Form window in windows)
            {
                if (window.IsDisposed || window.InvokeRequired || !window.Visible ||
                    window.WindowState == FormWindowState.Minimized || !window.Bounds.IntersectsWith(target)) continue;
                if (!SetSampleProperty(window.Handle, ManualSampleHidden, new IntPtr(1)))
                    throw new InvalidOperationException("The dashboard could not prepare a clean manual capture.");
                manualSampleWindows.Add(new KeyValuePair<Form, double>(window, window.Opacity));
                window.Opacity = 0;
            }
        }

        private bool HandleCaptureLeaseMessage(ref Message message)
        {
            if (message.Msg != BeginScreenSample && message.Msg != EndScreenSample && message.Msg != BeginManualScreenSample) return false;
            message.Result = IntPtr.Zero;
            long token = message.WParam.ToInt64();
            if (closing || screenCaptions == null || worker == null || token <= 0 || token > Int32.MaxValue)
                return true;
            try
            {
                if (worker.Id != message.LParam.ToInt64()) return true;
            }
            catch (InvalidOperationException) { return true; }

            if (message.Msg == EndScreenSample)
            {
                if (sampleToken == (int)token)
                {
                    ReleaseScreenSample();
                    message.Result = new IntPtr(1);
                }
                return true;
            }
            // A worker can exit or time out between Begin and End. Only the
            // latest ticket can restore this label set, and it has a finite life.
            if (sampleToken != 0) return true;
            if (sampleTimeout == null)
            {
                sampleTimeout = new Timer { Interval = 2200 };
                sampleTimeout.Tick += delegate { ReleaseScreenSample(); };
            }
            sampleToken = (int)token;
            sampleTimeout.Start();
            try
            {
                bool hidden = screenCaptions.BeginCapturePause();
                if (message.Msg == BeginManualScreenSample) PrepareManualScreenSample();
                if ((hidden || manualSampleWindows.Count > 0) && DwmFlush() < 0)
                    ReleaseScreenSample();
                else
                    message.Result = new IntPtr(1);
            }
            catch (Exception)
            {
                ReleaseScreenSample();
            }
            return true;
        }
    }
}
