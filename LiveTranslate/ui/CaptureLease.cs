using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed partial class MainForm
    {
        private const int BeginScreenSample = 0x8000 + 0x241;
        private const int EndScreenSample = BeginScreenSample + 1;
        private const string CaptureCoordinator = "LiveTranslate.ScreenSample.v1";
        private int sampleToken;
        private Timer sampleTimeout;

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
            if (!closing && screenCaptions != null) screenCaptions.EndCapturePause();
        }

        private bool HandleCaptureLeaseMessage(ref Message message)
        {
            if (message.Msg != BeginScreenSample && message.Msg != EndScreenSample) return false;
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
            bool hidden = screenCaptions.BeginCapturePause();
            if (hidden && DwmFlush() < 0)
                ReleaseScreenSample();
            else
                message.Result = new IntPtr(1);
            return true;
        }
    }
}
