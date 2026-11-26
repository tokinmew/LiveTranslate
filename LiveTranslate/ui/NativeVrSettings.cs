using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed partial class MainForm
    {
        NativeVrOverlay nativeVrOverlay;
        readonly Timer nativeVrTimer = new Timer { Interval = 200 };
        readonly ContextMenuStrip captionChoiceMenu = new ContextMenuStrip();
        Label nativeVrStatus;
        Button nativeVrStart, nativeVrStop;
        ThemedNumericUpDown nativeVrWidth, nativeVrDistance, nativeVrHeight;
        bool nativeVrReady, captionChoicePending;

        private void BuildNativeVrTab()
        {
            TabPage page = SettingsPage("VR captions");
            TableLayoutPanel rows = new TableLayoutPanel { Dock = DockStyle.Top, Height = 390,
                ColumnCount = 2, RowCount = 7, Margin = Padding.Empty };
            rows.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 170));
            rows.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            for (int i = 0; i < 5; i++) rows.RowStyles.Add(new RowStyle(SizeType.Absolute, 39));
            rows.RowStyles.Add(new RowStyle(SizeType.Absolute, 85));
            rows.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            nativeVrWidth = VrNumber(0.35M, 1.4M, 0.9M);
            nativeVrDistance = VrNumber(0.7M, 3.0M, 1.6M);
            nativeVrHeight = VrNumber(-0.9M, 0.2M, -0.4M);
            AddSetting(rows, 0, "Width (metres)", nativeVrWidth);
            AddSetting(rows, 1, "Distance (metres)", nativeVrDistance);
            AddSetting(rows, 2, "Vertical offset (metres)", nativeVrHeight);
            nativeVrStart = MakeButton("Start VR captions", delegate { StartNativeVrCaptions(); }, true);
            nativeVrStop = MakeButton("Stop VR captions", delegate { StopNativeVrCaptions("VR captions are off."); }, false);
            nativeVrStop.Enabled = false;
            rows.Controls.Add(nativeVrStart, 0, 3);
            rows.Controls.Add(nativeVrStop, 1, 3);
            Button desktop = MakeButton("Desktop captions", delegate { OpenVrCaptions(); }, false);
            rows.Controls.Add(desktop, 1, 4);
            nativeVrStatus = Note("Off. Connect your headset and launch VRChat through SteamVR, then start VR captions here.", secondaryInk);
            nativeVrStatus.AccessibleRole = AccessibleRole.StatusBar;
            nativeVrStatus.TextAlign = ContentAlignment.TopLeft;
            nativeVrStatus.Padding = new Padding(0, 7, 0, 0);
            rows.Controls.Add(nativeVrStatus, 0, 5); rows.SetColumnSpan(nativeVrStatus, 2);
            Label detail = Note("Captions follow your view, below centre. They stay in VR while the dashboard is minimized. " +
                "Choose VRChat under Capture area for screen reading; Preview capture shows the exact source. " +
                "Virtual Desktop must use SteamVR for this overlay. VDXR/OpenXR and standalone headset sessions are not supported yet.", secondaryInk);
            detail.TextAlign = ContentAlignment.TopLeft;
            detail.Font = new Font(Font.FontFamily, 9F);
            rows.Controls.Add(detail, 0, 6); rows.SetColumnSpan(detail, 2);
            AddSettingsBody(page, "Native SteamVR captions", "Display translations inside PC VR without attaching a desktop window or using a second monitor.", rows, 390);
            settingsTabs.TabPages.Add(page);
            ReadNativeVrPlacement();
            nativeVrWidth.ValueChanged += NativeVrPlacementChanged;
            nativeVrDistance.ValueChanged += NativeVrPlacementChanged;
            nativeVrHeight.ValueChanged += NativeVrPlacementChanged;
            nativeVrTimer.Tick += delegate { RefreshNativeVrCaption(); };
            Disposed += delegate {
                nativeVrTimer.Stop(); nativeVrTimer.Dispose();
                if (nativeVrOverlay != null) { nativeVrOverlay.Dispose(); nativeVrOverlay = null; }
                captionChoiceMenu.Dispose();
            };
            nativeVrReady = true;
        }

        private ThemedNumericUpDown VrNumber(decimal minimum, decimal maximum, decimal initial)
        {
            return new ThemedNumericUpDown { Minimum = minimum, Maximum = maximum, Value = initial,
                DecimalPlaces = 2, Increment = 0.05M, Width = 108 };
        }

        private string NativeVrPreferenceFile
        {
            get { return Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "config", "vr-overlay.json"); }
        }

        private void ReadNativeVrPlacement()
        {
            try
            {
                if (!File.Exists(NativeVrPreferenceFile) || new FileInfo(NativeVrPreferenceFile).Length > 4096) return;
                var saved = json.Deserialize<Dictionary<string, decimal>>(File.ReadAllText(NativeVrPreferenceFile));
                ReadVrNumber(saved, "width", nativeVrWidth);
                ReadVrNumber(saved, "distance", nativeVrDistance);
                ReadVrNumber(saved, "height", nativeVrHeight);
            }
            catch (Exception) { }
        }

        private static void ReadVrNumber(Dictionary<string, decimal> saved, string name, NumericUpDown control)
        {
            decimal value;
            if (saved != null && saved.TryGetValue(name, out value))
                control.Value = Math.Max(control.Minimum, Math.Min(control.Maximum, value));
        }

        private void NativeVrPlacementChanged(object sender, EventArgs e)
        {
            if (!nativeVrReady) return;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(NativeVrPreferenceFile));
                File.WriteAllText(NativeVrPreferenceFile, json.Serialize(new Dictionary<string, decimal> {
                    { "width", nativeVrWidth.Value }, { "distance", nativeVrDistance.Value }, { "height", nativeVrHeight.Value } }));
            }
            catch (Exception) { nativeVrStatus.Text = "Placement changed for this session; it could not be saved."; }
            if (nativeVrOverlay != null && nativeVrOverlay.IsRunning)
            {
                try { ApplyNativeVrPlacement(); nativeVrOverlay.ApplyPlacement(); }
                catch (Exception error) { StopNativeVrCaptions("VR captions stopped. " + error.GetBaseException().Message); }
            }
        }

        private void ApplyNativeVrPlacement()
        {
            nativeVrOverlay.WidthMeters = (float)nativeVrWidth.Value;
            nativeVrOverlay.DistanceMeters = (float)nativeVrDistance.Value;
            nativeVrOverlay.VerticalOffsetMeters = (float)nativeVrHeight.Value;
        }

        private void StartNativeVrCaptions()
        {
            if (closing || IsDisposed || Disposing) return;
            if (nativeVrOverlay != null && nativeVrOverlay.IsRunning) { OpenSettingsSection("VR captions"); return; }
            try
            {
                if (nativeVrOverlay == null) nativeVrOverlay = new NativeVrOverlay();
                ApplyNativeVrPlacement();
                string error;
                if (!nativeVrOverlay.Start(out error))
                {
                    StopNativeVrCaptions(error); OpenSettingsSection("VR captions"); return;
                }
                nativeVrStart.Enabled = false; nativeVrStop.Enabled = true;
                nativeVrStatus.Text = "SteamVR captions are on. Dashboard minimization does not stop them.";
                nativeVrTimer.Start();
                RefreshNativeVrCaption();
                SetStatus("Native SteamVR captions started. You can return to VRChat.");
            }
            catch (Exception error) { StopNativeVrCaptions("VR captions could not start. " + error.GetBaseException().Message); }
        }

        private void StopNativeVrCaptions(string message)
        {
            nativeVrTimer.Stop();
            if (nativeVrOverlay != null) nativeVrOverlay.Stop();
            if (nativeVrStart != null) nativeVrStart.Enabled = true;
            if (nativeVrStop != null) nativeVrStop.Enabled = false;
            if (nativeVrStatus != null) nativeVrStatus.Text = message;
        }

        private void RefreshNativeVrCaption()
        {
            if (closing || IsDisposed || nativeVrOverlay == null || !nativeVrOverlay.IsRunning) return;
            try
            {
                var originals = new List<string>();
                var translations = new List<string>();
                long now = VrCaptionWindow.Clock.ElapsedMilliseconds;
                for (int i = 0; i < VrCaptionState.Channels.Length; i++)
                {
                    string translated = vrCaptionState.Read(i, now);
                    if (String.IsNullOrEmpty(translated)) continue;
                    translations.Add(translated);
                    string original = vrCaptionState.Original(i, now);
                    if (!String.IsNullOrEmpty(original)) originals.Add(original);
                }
                nativeVrOverlay.Update(new NativeVrCaptionSnapshot { Status = SessionStatusText, Input = VrCaptureInput(),
                    Original = String.Join("\n", originals.ToArray()), Translation = String.Join("\n\n", translations.ToArray()) });
                string error;
                if (!nativeVrOverlay.Tick(out error)) StopNativeVrCaptions(error);
            }
            catch (Exception error) { StopNativeVrCaptions("VR captions stopped. " + error.GetBaseException().Message); }
        }

        private void ShowCaptionOptions()
        {
            if (closing || IsDisposed || captionChoicePending) return;
            captionChoiceMenu.Close();
            var old = new List<ToolStripItem>();
            foreach (ToolStripItem item in captionChoiceMenu.Items) old.Add(item);
            captionChoiceMenu.Items.Clear();
            foreach (ToolStripItem item in old) item.Dispose();
            captionChoiceMenu.Items.Add("Desktop captions", null, delegate { QueueCaptionChoice(OpenVrCaptions); });
            captionChoiceMenu.Items.Add("Native VR captions (SteamVR)", null, delegate { QueueCaptionChoice(StartNativeVrCaptions); });
            captionChoiceMenu.Items.Add("VR caption settings", null, delegate { QueueCaptionChoice(delegate { OpenSettingsSection("VR captions"); }); });
            MenuTheme.Apply(captionChoiceMenu);
            captionChoiceMenu.Show(sessionCaptionButton, new Point(0, sessionCaptionButton.Height));
        }

        private void QueueCaptionChoice(Action action)
        {
            if (closing || IsDisposed || Disposing || !IsHandleCreated || captionChoicePending) return;
            captionChoicePending = true;
            BeginInvoke((MethodInvoker)delegate {
                try { if (!closing && !IsDisposed && !Disposing) action(); }
                finally { captionChoicePending = false; }
            });
        }
    }
}
