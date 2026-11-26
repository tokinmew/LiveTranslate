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
        ComboBox nativeVrConnection;
        OpacitySlider nativeVrOpacity;
        Label nativeVrOpacityValue, nativeVrRuntime;
        VrConnectionProfiles nativeVrProfiles;
        string nativeVrProfile = "steamvr";
        bool nativeVrReady, captionChoicePending;

        private void BuildNativeVrTab()
        {
            TabPage page = SettingsPage("VR captions");
            TableLayoutPanel rows = new TableLayoutPanel { Dock = DockStyle.Top, Height = 515,
                ColumnCount = 2, RowCount = 10, Margin = Padding.Empty };
            rows.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 170));
            rows.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            for (int i = 0; i < 8; i++) rows.RowStyles.Add(new RowStyle(SizeType.Absolute, 39));
            rows.RowStyles.Add(new RowStyle(SizeType.Absolute, 85));
            rows.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            nativeVrWidth = VrNumber(0.35M, 1.4M, 0.9M);
            nativeVrDistance = VrNumber(0.7M, 3.0M, 1.6M);
            nativeVrHeight = VrNumber(-0.9M, 0.2M, -0.4M);
            nativeVrConnection = Combo(); nativeVrConnection.AccessibleName = "VR connection profile";
            for (int i = 0; i < VrConnectionProfiles.Codes.Length; i++)
                nativeVrConnection.Items.Add(new Choice(VrConnectionProfiles.Codes[i], VrConnectionProfiles.Names[i]));
            nativeVrConnection.SelectedIndex = 0;
            AddSetting(rows, 0, "VR connection", nativeVrConnection);
            nativeVrRuntime = Note("Runtime: checked when you open this page or start captions.", secondaryInk);
            nativeVrRuntime.Font = new Font(Font.FontFamily, 9F);
            rows.Controls.Add(nativeVrRuntime, 0, 1); rows.SetColumnSpan(nativeVrRuntime, 2);
            AddSetting(rows, 2, "Width (metres)", nativeVrWidth);
            AddSetting(rows, 3, "Distance (metres)", nativeVrDistance);
            AddSetting(rows, 4, "Vertical offset (metres)", nativeVrHeight);
            var opacity = Columns(0, 60);
            nativeVrOpacity = new OpacitySlider { Dock = DockStyle.Fill, Margin = new Padding(0, 0, 12, 5) };
            nativeVrOpacityValue = Note("95%", paperInk);
            opacity.Controls.Add(nativeVrOpacity, 0, 0); opacity.Controls.Add(nativeVrOpacityValue, 1, 0);
            AddSetting(rows, 5, "Background opacity", opacity);
            nativeVrStart = MakeButton("Start VR captions", delegate { StartNativeVrCaptions(); }, true);
            nativeVrStop = MakeButton("Stop VR captions", delegate { StopNativeVrCaptions("VR captions are off."); }, false);
            nativeVrStop.Enabled = false;
            rows.Controls.Add(nativeVrStart, 0, 6);
            rows.Controls.Add(nativeVrStop, 1, 6);
            Button desktop = MakeButton("Desktop captions", delegate { OpenVrCaptions(); }, false);
            rows.Controls.Add(desktop, 1, 7);
            nativeVrStatus = Note("Off. Connect your headset and launch VRChat through SteamVR, then start VR captions here.", secondaryInk);
            nativeVrStatus.AccessibleRole = AccessibleRole.StatusBar;
            nativeVrStatus.TextAlign = ContentAlignment.TopLeft;
            nativeVrStatus.Padding = new Padding(0, 7, 0, 0);
            rows.Controls.Add(nativeVrStatus, 0, 8); rows.SetColumnSpan(nativeVrStatus, 2);
            Label detail = Note("Placement and background opacity are saved separately for each connection. Text stays readable at 0% background opacity. " +
                "These profiles use SteamVR; choosing one does not switch your system runtime. " +
                "VDXR/OpenXR and standalone headset overlays are not supported yet.", secondaryInk);
            detail.TextAlign = ContentAlignment.TopLeft;
            detail.Font = new Font(Font.FontFamily, 9F);
            rows.Controls.Add(detail, 0, 9); rows.SetColumnSpan(detail, 2);
            AddSettingsBody(page, "Native SteamVR captions", "Choose your connection and caption layout. Captions continue while the dashboard is minimized.", rows, 515);
            settingsTabs.TabPages.Add(page);
            ReadNativeVrPlacement();
            nativeVrWidth.ValueChanged += NativeVrPlacementChanged;
            nativeVrDistance.ValueChanged += NativeVrPlacementChanged;
            nativeVrHeight.ValueChanged += NativeVrPlacementChanged;
            nativeVrOpacity.ValueChanged += NativeVrPlacementChanged;
            nativeVrConnection.SelectedIndexChanged += NativeVrConnectionChanged;
            settingsTabs.SelectedIndexChanged += delegate { if (settingsTabs.SelectedTab == page) RefreshNativeVrRuntime(); };
            nativeVrTimer.Tick += delegate { RefreshNativeVrCaption(); };
            Disposed += delegate {
                nativeVrTimer.Stop(); nativeVrTimer.Dispose();
                if (nativeVrOverlay != null) { nativeVrOverlay.Dispose(); nativeVrOverlay = null; }
                captionChoiceMenu.Dispose();
            };
            nativeVrReady = true;
            nativeVrStart.Enabled = nativeVrProfile != "openxr";
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
            nativeVrProfiles = VrConnectionProfiles.Read(NativeVrPreferenceFile);
            nativeVrProfile = nativeVrProfiles.Selected;
            SelectCode(nativeVrConnection, nativeVrProfile);
            LoadNativeVrLayout();
        }

        private void LoadNativeVrLayout()
        {
            bool ready = nativeVrReady; nativeVrReady = false;
            try
            {
                VrConnectionLayout saved = nativeVrProfiles.Get(nativeVrProfile);
                nativeVrWidth.Value = saved.width; nativeVrDistance.Value = saved.distance; nativeVrHeight.Value = saved.height;
                nativeVrOpacity.Value = saved.opacity; nativeVrOpacityValue.Text = saved.opacity + "%";
            }
            finally { nativeVrReady = ready; }
        }

        private void SaveNativeVrLayout()
        {
            VrConnectionLayout layout = nativeVrProfiles.Get(nativeVrProfile);
            layout.width = nativeVrWidth.Value; layout.distance = nativeVrDistance.Value;
            layout.height = nativeVrHeight.Value; layout.opacity = nativeVrOpacity.Value;
            nativeVrProfiles.Selected = nativeVrProfile;
            nativeVrProfiles.Write(NativeVrPreferenceFile);
        }

        private void NativeVrConnectionChanged(object sender, EventArgs e)
        {
            if (!nativeVrReady) return;
            // Preserve the outgoing layout before restoring the incoming profile.
            try { SaveNativeVrLayout(); } catch (Exception) { nativeVrStatus.Text = "The previous layout could not be saved."; }
            nativeVrProfile = SelectedCode(nativeVrConnection);
            nativeVrProfiles.Selected = nativeVrProfile;
            LoadNativeVrLayout(); NativeVrPlacementChanged(sender, e);
            if (nativeVrProfile == "openxr") StopNativeVrCaptions("OpenXR/VDXR native captions are not available yet. Use a SteamVR connection or desktop captions.");
            nativeVrStart.Enabled = nativeVrProfile != "openxr" && (nativeVrOverlay == null || !nativeVrOverlay.IsRunning);
            RefreshNativeVrRuntime();
        }

        private void RefreshNativeVrRuntime()
        {
            bool running = false;
            try
            {
                foreach (System.Diagnostics.Process process in System.Diagnostics.Process.GetProcessesByName("vrserver"))
                    using (process) { if (!process.HasExited) running = true; }
            }
            catch (Exception) { }
            nativeVrRuntime.Text = nativeVrProfile == "openxr" ? "Selected runtime: OpenXR / VDXR. Native overlay support is pending." :
                running ? "Runtime: SteamVR is running. Headset connection is checked when captions start." :
                "Runtime: SteamVR is not running. Start it with your headset connected.";
        }

        private void NativeVrPlacementChanged(object sender, EventArgs e)
        {
            if (!nativeVrReady) return;
            try
            {
                SaveNativeVrLayout();
            }
            catch (Exception) { nativeVrStatus.Text = "Placement changed for this session; it could not be saved."; }
            nativeVrOpacityValue.Text = nativeVrOpacity.Value + "%";
            if (nativeVrOverlay != null && nativeVrOverlay.IsRunning)
            {
                try { ApplyNativeVrPlacement(); nativeVrOverlay.ApplyPlacement(); }
                catch (Exception error) { StopNativeVrCaptions("VR captions stopped. " + error.GetBaseException().Message); }
            }
            RefreshNativeVrCaption();
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
            if (nativeVrProfile == "openxr")
            { StopNativeVrCaptions("This connection needs an OpenXR/VDXR overlay backend. Choose a SteamVR connection or desktop captions."); OpenSettingsSection("VR captions"); return; }
            if (nativeVrOverlay != null && nativeVrOverlay.IsRunning) { OpenSettingsSection("VR captions"); return; }
            try
            {
                if (nativeVrOverlay == null) nativeVrOverlay = new NativeVrOverlay();
                ApplyNativeVrPlacement();
                nativeVrOverlay.Update(BuildNativeVrCaption());
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
            if (nativeVrStart != null) nativeVrStart.Enabled = nativeVrProfile != "openxr";
            if (nativeVrStop != null) nativeVrStop.Enabled = false;
            if (nativeVrStatus != null) nativeVrStatus.Text = message;
        }

        private void RefreshNativeVrCaption()
        {
            if (closing || IsDisposed || nativeVrOverlay == null || !nativeVrOverlay.IsRunning) return;
            try
            {
                nativeVrOverlay.Update(BuildNativeVrCaption());
                string error;
                if (!nativeVrOverlay.Tick(out error)) StopNativeVrCaptions(error);
            }
            catch (Exception error) { StopNativeVrCaptions("VR captions stopped. " + error.GetBaseException().Message); }
        }

        private NativeVrCaptionSnapshot BuildNativeVrCaption()
        {
                var originals = new List<string>();
                var translations = new List<string>();
                var sources = new List<string>();
                long now = VrCaptionWindow.Clock.ElapsedMilliseconds;
                for (int i = 0; i < VrCaptionState.Channels.Length; i++)
                {
                    string translated = vrCaptionState.Read(i, now);
                    if (String.IsNullOrEmpty(translated)) continue;
                    translations.Add(translated);
                    string source = vrCaptionState.SourceLabel(i, now);
                    if (!String.IsNullOrEmpty(source)) sources.Add(source);
                    string original = vrCaptionState.Original(i, now);
                    if (!String.IsNullOrEmpty(original)) originals.Add(original);
                }
                return new NativeVrCaptionSnapshot { Status = SessionStatusText,
                    Input = sources.Count == 0 ? VrCaptureInput() : String.Join(" · ", sources.ToArray()),
                    Original = String.Join("\n", originals.ToArray()), Translation = String.Join("\n\n", translations.ToArray()),
                    BackgroundOpacity = nativeVrOpacity.Value };
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
