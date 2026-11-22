using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Live Translate")]
[assembly: System.Reflection.AssemblyProduct("Live Translate")]
[assembly: System.Reflection.AssemblyDescription("Private live audio, screen, and text translation into English")]
[assembly: System.Reflection.AssemblyVersion("0.6.6.0")]
[assembly: System.Reflection.AssemblyFileVersion("0.6.6.0")]
namespace LiveTranslate
{
    internal static class Program
    {
        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();
        [DllImport("user32.dll")]
        private static extern bool SetProcessDpiAwarenessContext(IntPtr value);
        [STAThread]
        private static void Main()
        {
            bool ready = false;
            try
            {
                ready = SetProcessDpiAwarenessContext(new IntPtr(-4));
            }
            catch
            {
            }

            if (!ready)
                try
                {
                    SetProcessDPIAware();
                }
                catch
                {
                }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            if (UpdateStartup.HandOffIfBusy()) return;
            Application.Run(new MainForm());
        }
    }

    internal sealed class Choice
    {
        public string Code;
        public string Name;
        public int DeviceId;
        public Choice(string code, string name)
        {
            Code = code;
            Name = name;
        }

        public override string ToString()
        {
            return Name;
        }
    }

    internal sealed class PendingRequest
    {
        public string Command;
        public string Session;
        public string Channel;
        public string TypedText, TypedSource;
        public PendingRequest(string command, string session, string channel)
        {
            Command = command;
            Session = session;
            Channel = channel;
        }
    }

    internal sealed class CaptionEntry
    {
        public string Label;
        public string Text;
        public string Original;
        public string Time;
        public int RenderedLength;
        public CaptionEntry(string label, string text, string original)
        {
            Label = label;
            Text = text;
            Original = original;
            Time = DateTime.Now.ToString("HH:mm:ss");
        }
    }

    internal sealed partial class MainForm : Form
    {
        private readonly Color background = Color.FromArgb(237, 243, 241);
        private readonly Color surface = Color.FromArgb(23, 45, 48);
        private readonly Color field = Color.FromArgb(39, 67, 69);
        private readonly Color ink = Color.FromArgb(249, 250, 254);
        private readonly Color muted = Color.FromArgb(191, 213, 208);
        private readonly Color accent = Color.FromArgb(116, 225, 194);
        private readonly Color border = Color.FromArgb(61, 88, 89);
        private readonly Color paper = Color.White;
        private readonly Color paperInk = Color.FromArgb(23, 48, 51);
        private readonly Color secondaryInk = Color.FromArgb(74, 99, 101);
        private readonly Color violet = Color.FromArgb(17, 107, 96);
        private readonly JavaScriptSerializer json = new JavaScriptSerializer();
        private readonly object writeLock = new object ();
        private readonly Dictionary<int, PendingRequest> pending = new Dictionary<int, PendingRequest>();
        private readonly Dictionary<string, Dictionary<string, object>> profiles = new Dictionary<string, Dictionary<string, object>>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, Dictionary<string, object>> languageMetadata = new Dictionary<string, Dictionary<string, object>>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, string> speechOverrides = new Dictionary<string, string>();
        private readonly Dictionary<string, string> ocrOverrides = new Dictionary<string, string>();
        private readonly List<CaptionEntry> history = new List<CaptionEntry>();
        private readonly HashSet<string> speechModels = new HashSet<string>();
        private readonly HashSet<string> speechSources = new HashSet<string>();
        private readonly HashSet<string> ocrModels = new HashSet<string>();
        private bool ocrEngineReady, hasOcrStatus, speechModelChosen;
        private string checkedOcrPath = "";
        private const string DialogueInstaller = "Install Korean dialogue.cmd";
        private enum ComponentSetup { Standard, Quality, KoreanDialogue }
        private readonly Font captionFont = new Font("Segoe UI", 16F);
        private readonly Font labelFont = new Font("Segoe UI", 8.5F, FontStyle.Bold);
        private readonly Font sourceFont = new Font("Segoe UI", 10F);
        private Process worker, installer;
        private StreamWriter inputWriter;
        private int requestId;
        private bool closing, connected, profileBusy, applyingProfile, updatingDevices, updatingToggles, oneShotPending;
        private bool audioWanted, screenWanted, devicesReady;
        // Watching is armed on launch, including when installation is still in progress.
        // Keep intent separate from whether a real worker session is actually running.
        private bool screenArmed = true, selectingArea, displayChangePending;
        private int failedConnections;
        private DateTime reconnectAfterUtc;
        private readonly System.Windows.Forms.Timer readinessTimer = new System.Windows.Forms.Timer();
        private string targetDisplay;
        private readonly CaptionOverlay captionOverlay = new CaptionOverlay();
        private readonly ScreenCaptionLayer screenCaptions = new ScreenCaptionLayer();
        private string audioSession = "", screenSession = "", onceSession = "";
        private string pendingInstallCommand, pendingInstallLanguage, stderrTail = "", setupTail = "";
        private ComboBox profileSelector, devices, audioModel, koreanDialogue, customTextSource, japaneseDirection;
        private TextBox audioLanguage, ocrLanguage, tesseractPath, input;
        private NumericUpDown chunks, threads;
        private ModernSwitch audioToggle, screenToggle;
        private Button setupProfile, setupAll, setupComponents, readOnce, selectArea;
        private Label profileHint, profileReadiness, engineBadge, status, audioStateLabel, screenStateLabel, regionLabel, emptyOutput, packSummary;
        private RichTextBox output;
        private CheckBox showSource, overlayToggle;
        private Form settingsForm;
        private TabControl settingsTabs;
        private Rectangle? selectedRegion;
        public MainForm()
        {
            Text = "Live Translate";
            try
            {
                Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            }
            catch
            {
            }

            SuspendLayout();
            Font = new Font("Segoe UI", 10F);
            BackColor = background;
            ForeColor = ink;
            AutoScaleDimensions = new SizeF(96F, 96F);
            AutoScaleMode = AutoScaleMode.Dpi;
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(1190, 760);
            MinimumSize = new Size(790, 550);
            json.MaxJsonLength = 4 * 1024 * 1024;
            BindCaptionLayers();
            BuildSettings();
            BuildUpdatesTab();
            BuildSpokenTab();
            BuildUi();
            ResumeLayout(true);
            Load += delegate { FitToDisplay(this); };
            ApplyProfile(false);
            UpdateControls();
            Shown += delegate
            {
                StartWorker();
                readinessTimer.Interval = 10000;
                readinessTimer.Tick += CheckForScreenSetup;
                readinessTimer.Start();
            };
            FormClosing += OnClosing;
        }

        private static string NewSession()
        {
            return Guid.NewGuid().ToString("N");
        }

        private string ProfileCode()
        {
            return SelectedCode(profileSelector);
        }

        private bool PriorityProfile(string code)
        {
            return code == "zt" || code == "zh" || code == "ko" || code == "ja";
        }

        private string ProfileName(string code)
        {
            if (code == "auto")
                return "Automatic";
            if (code == "zt")
                return "Traditional Chinese";
            if (code == "zh")
                return "Simplified Chinese";
            if (code == "ko")
                return "Korean";
            if (code == "ja")
                return "Japanese";
            if (code == "other")
                return "Custom language";
            if (code == "mul")
                return "Multiple languages";
            Dictionary<string, object> meta;
            return profiles.TryGetValue(code, out meta) || languageMetadata.TryGetValue(code, out meta) ? Value(meta, "name") : code;
        }

        private void SelectProfile(string code)
        {
            SelectCode(profileSelector, code);
        }

        private string TextSource()
        {
            return ProfileCode() == "other" ? SelectedCode(customTextSource) : ProfileCode();
        }

        private void ProfileChanged()
        {
            if (applyingProfile)
                return;
            ApplyProfile(true);
        }

        private void ApplyProfile(bool restart)
        {
            if (profileSelector == null || japaneseDirection == null)
                return;
            applyingProfile = true;
            try
            {
                string code = ProfileCode(), speech = "", ocr = "";
                Dictionary<string, object> meta;
                if (code == "auto")
                {
                    speech = "auto";
                    ocr = "auto";
                }
                else if (code == "zt")
                {
                    speech = "zh";
                    ocr = "chi_tra";
                }
                else if (code == "zh")
                {
                    speech = "zh";
                    ocr = "chi_sim";
                }
                else if (code == "ko")
                {
                    speech = "ko";
                    ocr = "kor";
                }
                else if (code == "ja")
                {
                    speech = "ja";
                    ocr = SelectedCode(japaneseDirection) == "vertical" ? "jpn_vert" : "jpn";
                }
                else if (profiles.TryGetValue(code, out meta) || languageMetadata.TryGetValue(code, out meta))
                {
                    speech = Value(meta, "speech_language");
                    ocr = Value(meta, "ocr_language");
                }

                if (speechOverrides.ContainsKey(code))
                    speech = speechOverrides[code];
                if (ocrOverrides.ContainsKey(code))
                    ocr = ocrOverrides[code];
                audioLanguage.Text = speech;
                ocrLanguage.Text = ocr;
                bool editable = code == "other";
                audioLanguage.ReadOnly = !editable;
                ocrLanguage.ReadOnly = !editable;
                audioLanguage.BackColor = ocrLanguage.BackColor = editable ? SystemColors.Window : SystemColors.Control;
                customTextSource.Enabled = code == "other";
                japaneseDirection.Visible = code == "ja";
                if (code != "other")
                    SelectCode(customTextSource, code);
                if (code == "auto")
                    profileHint.Text = "Auto-detect speech and text. Screen watches Chinese, Korean and Japanese.";
                else if (code == "zt")
                    profileHint.Text = "Traditional Chinese text and Mandarin speech";
                else if (PriorityProfile(code))
                    profileHint.Text = ProfileName(code) + " to English";
                else if (code == "other")
                    profileHint.Text = "Choose an imported text language in Settings.";
                else
                    profileHint.Text = ProfileName(code) + " to English";
                RefreshReadiness();
                UpdateControls();
            }
            finally
            {
                applyingProfile = false;
            }

            if (restart)
            {
                if (settingsForm.Visible) RememberProcessingSettings();
                SetStatus("Source changed to " + ProfileName(ProfileCode()) + ". Existing English captions are kept.");
                CancelReadOnce();
                if (audioWanted)
                    RestartAudio();
                ReconfigureScreen();
            }
        }

        private void ApplySettings()
        {
            bool speechChanged = initialSpeechSettings == null || !System.Linq.Enumerable.SequenceEqual(initialSpeechSettings, SpeechSettingsValues());
            bool screenChanged = initialScreenSettings == null || !System.Linq.Enumerable.SequenceEqual(initialScreenSettings, ScreenSettingsValues());
            if (!speechChanged && !screenChanged) { settingsForm.Hide(); return; }
            string code = ProfileCode();
            if (code == "other")
            {
                speechOverrides[code] = audioLanguage.Text.Trim();
                ocrOverrides[code] = ocrLanguage.Text.Trim();
            }

            ApplyProfile(false);
            if (connected && !String.Equals(checkedOcrPath, tesseractPath.Text.Trim(), StringComparison.OrdinalIgnoreCase))
                Send("status", null);
            if (screenChanged) CancelReadOnce();
            SetStatus("Settings applied.");
            settingsForm.Hide();
            if (speechChanged && audioWanted)
                RestartAudio();
            if (screenChanged) ReconfigureScreen();
        }

        private void AudioToggleChanged(object sender, EventArgs e)
        {
            if (updatingToggles)
                return;
            audioWanted = audioToggle.Checked;
            if (audioWanted)
                RestartAudio();
            else
                StopAudio();
        }

        private void ScreenToggleChanged(object sender, EventArgs e)
        {
            if (updatingToggles)
                return;
            screenArmed = screenToggle.Checked;
            if (screenArmed)
            {
                TryStartScreen();
            }
            else
            {
                StopScreen();
                CancelReadOnce();
            }
            UpdateControls();
        }

        private void SetSwitch(ModernSwitch toggle, bool value)
        {
            updatingToggles = true;
            try
            {
                toggle.Checked = value;
            }
            finally
            {
                updatingToggles = false;
            }
        }

        private void RestartAudio()
        {
            ClearOverlayChannel("audio");
            InvalidateRequests("audio");
            audioSession = NewSession();
            if (connected)
                Send("stop_audio", null);
            if (!audioWanted)
                return;
            Choice device = devices.SelectedItem as Choice;
            if (!connected || !devicesReady || device == null)
            {
                audioWanted = false;
                SetSwitch(audioToggle, false);
                audioStateLabel.Text = !connected ? "Local engine unavailable." : !devicesReady ? "Checking available audio devices..." : "Choose an audio device, then enable listening.";
                SetStatus(audioStateLabel.Text);
                UpdateControls();
                return;
            }

            if (!SpeechModelSupportsSelection() || !speechModels.Contains(Convert.ToString(audioModel.SelectedItem)))
            {
                audioWanted = false;
                SetSwitch(audioToggle, false);
                audioStateLabel.Text = !SpeechModelSupportsSelection()
                    ? "The selected speech model does not support this language."
                    : koreanDialogue.SelectedIndex == 1
                    ? "Install Quality speech in Settings to add the Small model."
                    : "Speech model needed. Choose Install all four.";
                SetStatus(audioStateLabel.Text);
                UpdateControls();
                return;
            }

            audioStateLabel.Text = "Starting device and loading the speech model...";
            if (!Send("start_audio", AudioStartOptions(device.DeviceId)))
            {
                audioWanted = false;
                SetSwitch(audioToggle, false);
            }

            UpdateControls();
        }

        private Dictionary<string, object> AudioStartOptions(int deviceId)
        {
            var options = Dict("device_id", deviceId, "model", Convert.ToString(audioModel.SelectedItem),
                "language", audioLanguage.Text.Trim().ToLowerInvariant(), "chunk_seconds", (int)chunks.Value,
                "threads", (int)threads.Value, "session_id", audioSession);
            if (koreanDialogue.SelectedIndex == 1 && (ProfileCode() == "ko" || ProfileCode() == "auto"))
                options["korean_dialogue"] = "nvidia";
            return options;
        }

        private bool SpeechModelSupportsSelection()
        {
            string source = audioLanguage == null ? "" : audioLanguage.Text.Trim().ToLowerInvariant();
            if (source == "auto") return true;
            if (source == "" || source == "en" || (source == "yue" && !Object.Equals(audioModel.SelectedItem, "large-v3")))
                return false;
            return PriorityProfile(source) || speechSources.Contains(source);
        }

        private void StopAudio()
        {
            ClearOverlayChannel("audio");
            audioWanted = false;
            InvalidateRequests("audio");
            audioSession = NewSession();
            SetSwitch(audioToggle, false);
            if (connected)
                Send("stop_audio", null);
            audioStateLabel.Text = "Off. No audio is being captured.";
            UpdateControls();
        }

        private string ScreenProfile()
        {
            string code = ProfileCode();
            return code == "other" ? SelectedCode(customTextSource) : code;
        }

        private bool ScreenModelsReady()
        {
            string source = ScreenProfile();
            if (!String.Equals(checkedOcrPath, tesseractPath.Text.Trim(), StringComparison.OrdinalIgnoreCase))
                return false;
            foreach (KeyValuePair<string, Dictionary<string, object>> entry in profiles)
            {
                if (source == "auto" ? !PriorityProfile(entry.Key) : entry.Key != source)
                    continue;
                if (!hasOcrStatus)
                {
                    if (Flag(entry.Value, "screen_ready"))
                        return true;
                    continue;
                }
                string ocr = source == "ja" && SelectedCode(japaneseDirection) == "vertical" ? "jpn_vert" : Value(entry.Value, "ocr_language");
                if (ocrEngineReady && ocrModels.Contains(ocr) && Flag(entry.Value, "text_ready"))
                    return true;
            }
            return false;
        }

        private Screen CaptureDisplay()
        {
            if (targetDisplay == null)
                return Screen.PrimaryScreen;
            foreach (Screen screen in Screen.AllScreens)
                if (String.Equals(screen.DeviceName, targetDisplay, StringComparison.OrdinalIgnoreCase))
                    return screen;
            return null;
        }

        private Rectangle CaptureBounds()
        {
            if (selectedRegion.HasValue)
            {
                Rectangle region = selectedRegion.Value;
                if (SystemInformation.VirtualScreen.Contains(region))
                    foreach (Screen screen in Screen.AllScreens)
                        if (screen.Bounds.IntersectsWith(region))
                            return region;
                return Rectangle.Empty;
            }
            Screen display = CaptureDisplay();
            return display == null ? Rectangle.Empty : display.Bounds;
        }

        private Dictionary<string, object> ScreenArguments(string session)
        {
            Rectangle r = CaptureBounds();
            string source = ScreenProfile();
            Dictionary<string, object> region = !selectedRegion.HasValue && targetDisplay == null ? Dict("monitor", "primary") :
                Dict("left", r.Left, "top", r.Top, "width", r.Width, "height", r.Height);
            if (!selectedRegion.HasValue && targetDisplay != null)
                region["full_display"] = true;
            // The backend also enumerates source-caption windows on this GUI thread.
            var exclusions = new List<long> { Handle.ToInt64(), settingsForm.Handle.ToInt64(), captionOverlay.CaptureWindowId };
            long vrHandle = VrCaptionHandle();
            if (vrHandle != 0) exclusions.Add(vrHandle);
            return Dict("region", region, "ocr_language", source == "auto" ? "auto" : ocrLanguage.Text.Trim(),
                "source", source, "vertical", source == "ja" && SelectedCode(japaneseDirection) == "vertical",
                "interval", 0.5, "exclude_windows", exclusions, "tesseract_path", tesseractPath.Text.Trim(), "session_id", session);
        }

        private void TryStartScreen()
        {
            if (closing || selectingArea || !screenArmed || screenWanted || SetupRunning() || profileBusy)
                return;
            if (!connected || !ScreenModelsReady())
            {
                screenStateLabel.Text = ScreenProfile() == "auto" ? "Waiting for Chinese, Korean or Japanese screen files."
                    : "Screen captions need a local recognizer and text model for " + ProfileName(ScreenProfile()) + ".";
                return;
            }

            if (CaptureBounds().IsEmpty)
            {
                screenStateLabel.Text = selectedRegion.HasValue
                    ? "Waiting for the selected area. Restore the display or choose a new area."
                    : "Waiting for the selected display. Reconnect it or choose another display.";
                return;
            }
            screenSession = NewSession();
            screenWanted = true;
            screenStateLabel.Text = "Starting foreign-language recognition...";
            if (!Send("start_screen", ScreenArguments(screenSession)))
            {
                screenWanted = false;
                screenArmed = false;
                screenStateLabel.Text = "Screen capture could not start. Turn it on to retry.";
            }

            UpdateControls();
        }

        private void CheckForScreenSetup(object sender, EventArgs e)
        {
            if (closing || screenWanted || selectingArea || SetupRunning() || profileBusy)
                return;
            if (connected)
            {
                if (!screenArmed && ScreenModelsReady())
                    return;
                foreach (PendingRequest request in pending.Values)
                    if (request.Command == "status")
                        return;
                Send("status", null);
            }
            else if ((worker == null || worker.HasExited) && DateTime.UtcNow >= reconnectAfterUtc && RuntimeReady())
                StartWorker();
        }

        private void DelayReconnect()
        {
            failedConnections = Math.Min(5, failedConnections + 1);
            reconnectAfterUtc = DateTime.UtcNow.AddSeconds(Math.Min(120, 10 * (1 << (failedConnections - 1))));
        }

        private void ReconfigureScreen()
        {
            if (screenWanted)
                StopScreen();
            else
                ClearOverlayChannel("screen");
            TryStartScreen();
            UpdateControls();
        }

        private void StopScreen()
        {
            bool active = screenWanted;
            screenWanted = false;
            ClearOverlayChannel("screen");
            InvalidateRequests("screen");
            screenSession = NewSession();
            if (active && connected)
                Send("stop_screen", null);
            screenStateLabel.Text = "Paused. Read once scans a single frame.";
            UpdateControls();
        }

        private void ReadScreenOnce(object sender, EventArgs e)
        {
            if (!connected || !ScreenModelsReady() || CaptureBounds().IsEmpty)
            {
                SetStatus("Screen reading needs a display and installed language models.");
                return;
            }
            CancelReadOnce();
            onceSession = NewSession();
            oneShotPending = true;
            UpdateControls();
            if (!Send("read_screen_once", ScreenArguments(onceSession)))
            {
                oneShotPending = false;
                UpdateControls();
            }
        }

        private void CancelReadOnce()
        {
            InvalidateRequests("screen_once");
            onceSession = NewSession();
            oneShotPending = false;
            if (connected)
                Send("cancel_read_screen_once", null);
            UpdateControls();
        }

        private void SelectRegion(object sender, EventArgs e)
        {
            selectingArea = true;
            StopScreen();
            CancelReadOnce();
            ClearOverlayChannel("screen");
            bool restoreTop = TopMost;
            Hide();
            try
            {
                using (RegionPicker picker = new RegionPicker())
                    if (picker.ShowDialog() == DialogResult.OK)
                    {
                        selectedRegion = picker.Selection;
                        targetDisplay = null;
                        UpdateRegionLabel();
                    }
            }
            finally
            {
                Show();
                TopMost = restoreTop;
                selectingArea = false;
            }

            TryStartScreen();
            UpdateControls();
        }

        private void ChooseTarget(object sender, EventArgs e)
        {
            ContextMenuStrip menu = new ContextMenuStrip();
            ToolStripMenuItem primary = new ToolStripMenuItem("Primary display", null, delegate { SelectDisplay(null); });
            primary.Checked = !selectedRegion.HasValue && targetDisplay == null;
            menu.Items.Add(primary);
            int number = 0;
            foreach (Screen screen in Screen.AllScreens)
            {
                number++;
                if (screen.Primary)
                    continue;
                string device = screen.DeviceName;
                string title = String.Format("Display {0} ({1} × {2})", number, screen.Bounds.Width, screen.Bounds.Height);
                ToolStripMenuItem item = new ToolStripMenuItem(title, null, delegate { SelectDisplay(device); });
                item.Checked = !selectedRegion.HasValue && targetDisplay == device;
                menu.Items.Add(item);
            }
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Draw an area…", null, SelectRegion);
            menu.Closed += delegate { menu.Dispose(); };
            menu.Show(selectArea, new Point(0, selectArea.Height));
        }

        private void SelectDisplay(string device)
        {
            selectedRegion = null;
            targetDisplay = device;
            UpdateRegionLabel();
            CancelReadOnce();
            ReconfigureScreen();
        }

        private void UpdateRegionLabel()
        {
            if (CaptureBounds().IsEmpty)
                regionLabel.Text = selectedRegion.HasValue ? "Selected area unavailable" : "Selected display unavailable";
            else if (selectedRegion.HasValue)
                regionLabel.Text = String.Format("Area · {0} × {1}", selectedRegion.Value.Width, selectedRegion.Value.Height);
            else if (targetDisplay == null)
                regionLabel.Text = "Primary display";
            else
            {
                Screen display = CaptureDisplay();
                regionLabel.Text = display == null ? "No display" : "Display " + display.DeviceName.Replace(@"\\.\DISPLAY", "");
            }
        }

        protected override void WndProc(ref Message m)
        {
            if (HandleCaptureLeaseMessage(ref m)) return;
            const int displayChanged = 0x007E;
            base.WndProc(ref m);
            if (m.Msg != displayChanged || closing || displayChangePending || !IsHandleCreated || regionLabel == null)
                return;
            displayChangePending = true;
            Ui(delegate
            {
                displayChangePending = false;
                if (closing || selectingArea)
                    return;
                UpdateRegionLabel();
                CancelReadOnce();
                ReconfigureScreen();
            });
        }

        private void BindCaptionLayers()
        {
            captionOverlay.SourceBounds = delegate { return screenCaptions.VisibleBounds; };
            screenCaptions.LayoutChanged += captionOverlay.RepositionSpeech;
        }

        private void OverlayPreferenceChanged()
        {
            screenCaptions.SetEnabled(overlayToggle.Checked);
            if (!overlayToggle.Checked) captionOverlay.ClearCaption();
        }

        private void ClearOverlayChannel(string channel)
        {
            if (channel == "" || channel == "audio") StopSpoken();
            ClearVrCaption(channel);
            if (channel == "" || channel == "screen") screenCaptions.Clear();
            if (channel == "" || channel == "audio") captionOverlay.ClearCaption();
        }

        private static Dictionary<string, object> Dict(params object[] values)
        {
            Dictionary<string, object> result = new Dictionary<string, object>();
            for (int i = 0; i + 1 < values.Length; i += 2)
                result[Convert.ToString(values[i])] = values[i + 1];
            return result;
        }

        private static string Value(Dictionary<string, object> obj, string key)
        {
            object value;
            return obj.TryGetValue(key, out value) && value != null ? Convert.ToString(value) : "";
        }

        private static IEnumerable Items(Dictionary<string, object> obj, string key)
        {
            object value;
            return obj.TryGetValue(key, out value) && value is IEnumerable && !(value is string) ? (IEnumerable)value : new object[0];
        }

        private static string SelectedCode(ComboBox combo)
        {
            Choice choice = combo.SelectedItem as Choice;
            return choice == null ? "auto" : choice.Code;
        }

        private static void SelectCode(ComboBox combo, string code)
        {
            for (int i = 0; i < combo.Items.Count; i++)
                if (((Choice)combo.Items[i]).Code == code)
                {
                    combo.SelectedIndex = i;
                    return;
                }

            combo.SelectedIndex = combo.Items.Count > 0 ? 0 : -1;
        }

        private bool Flag(Dictionary<string, object> obj, string key)
        {
            object value;
            return obj.TryGetValue(key, out value) && value is bool && (bool)value;
        }

        private bool CurrentSession(string channel, string session)
        {
            if (session == "")
                return false;
            if (channel == "audio")
                return audioWanted && session == audioSession;
            if (channel == "screen")
                return screenWanted && session == screenSession;
            if (channel == "screen_once")
                return oneShotPending && session == onceSession;
            return false;
        }

        private string ChannelOf(string command)
        {
            if (command == "start_audio")
                return "audio";
            if (command == "start_screen")
                return "screen";
            if (command == "read_screen_once")
                return "screen_once";
            return "";
        }

        private void InvalidateRequests(string channel)
        {
            List<int> remove = new List<int>();
            foreach (KeyValuePair<int, PendingRequest> item in pending)
                if (item.Value.Channel == channel)
                    remove.Add(item.Key);
            foreach (int id in remove)
                pending.Remove(id);
        }

        private void HandleMessage(Dictionary<string, object> message)
        {
            string type = Value(message, "type"), session = Value(message, "session_id"), channel = Value(message, "channel");
            PendingRequest request = null;
            int responseId;
            if (Int32.TryParse(Value(message, "id"), out responseId) && pending.TryGetValue(responseId, out request))
            {
                pending.Remove(responseId);
                if (request.Command == "translate") UpdateTranslateAction();
            }
            if (channel == "" && (type == "audio" || type == "screen" || type == "screen_once"))
                channel = type;
            if (session == "" && request != null && request.Session != "")
            {
                session = request.Session;
                channel = request.Channel;
            }

            if ((session != "" || type == "capture_state" || type == "audio" || type == "screen" || type == "screen_once" || type == "screen_clear") && !CurrentSession(channel, session))
                return;
            if (type == "status" && Value(message, "topic") == "korean_dialogue")
            {
                string state = Value(message, "state");
                string detail = Value(message, "message");
                if (channel == "audio" && CurrentSession("audio", session) && detail != "" &&
                    (state == "loading" || state == "ready" || state == "fallback"))
                    audioStateLabel.Text = detail;
                return;
            }
            if (type == "status" && message.ContainsKey("installed_languages"))
            {
                bool firstStatus = !connected;
                connected = true;
                failedConnections = 0;
                bool previouslyHadSmall = speechModels.Contains("small");
                speechModels.Clear();
                foreach (object model in Items(message, "speech_models"))
                {
                    string name = Convert.ToString(model);
                    speechModels.Add(name);
                    if (!audioModel.Items.Contains(name)) audioModel.Items.Add(name);
                }
                if (!previouslyHadSmall && speechModels.Contains("small") && !speechModelChosen)
                {
                    audioModel.SelectedItem = "small";
                    threads.Value = Math.Min(2, Environment.ProcessorCount);
                }
                ocrModels.Clear();
                foreach (object model in Items(message, "ocr_languages"))
                    ocrModels.Add(Convert.ToString(model));
                hasOcrStatus = message.ContainsKey("ocr_languages") && message.ContainsKey("ocr_engine_ready");
                ocrEngineReady = Flag(message, "ocr_engine_ready");
                checkedOcrPath = Value(message, "tesseract_path");
                languageMetadata.Clear();
                foreach (object value in Items(message, "installed_languages"))
                {
                    Dictionary<string, object> item = value as Dictionary<string, object>;
                    if (item != null && Value(item, "code") != "")
                        languageMetadata[Value(item, "code")] = item;
                }

                profiles.Clear();
                speechSources.Clear();
                foreach (object value in Items(message, "profiles"))
                {
                    Dictionary<string, object> item = value as Dictionary<string, object>;
                    if (item != null && Value(item, "code") != "")
                    {
                        profiles[Value(item, "code")] = item;
                        string speech = Value(item, "speech_language");
                        if (speech != "" && speech != "en") speechSources.Add(speech);
                    }
                }

                bool editingCustom = settingsForm.Visible && ProfileCode() == "other";
                string draftSpeech = editingCustom ? audioLanguage.Text : null;
                string draftOcr = editingCustom ? ocrLanguage.Text : null;
                FillProfiles();
                FillCustomSources();
                ApplyProfile(false);
                if (editingCustom && ProfileCode() == "other")
                {
                    audioLanguage.Text = draftSpeech;
                    ocrLanguage.Text = draftOcr;
                }
                packSummary.Text = languageMetadata.Count + " individual text packs. Multilingual text model "
                    + (Flag(message, "multilingual_text_ready") ? "ready." : "not installed.") + "\nSpeech models: "
                    + (speechModels.Count == 0 ? "none" : String.Join(", ", new List<string>(speechModels).ToArray()));
                if (firstStatus)
                    SetStatus("Local engine ready. Audio is off.");
                if (pendingInstallCommand != null)
                {
                    string cmd = pendingInstallCommand, lang = pendingInstallLanguage;
                    pendingInstallCommand = null;
                    pendingInstallLanguage = null;
                    StartInstall(cmd, lang);
                }
                else if (!selectingArea)
                {
                    if (screenWanted && !ScreenModelsReady())
                        StopScreen();
                    TryStartScreen();
                    UpdateControls();
                }
            }
            else if (type == "devices")
            {
                devicesReady = true;
                Choice oldDevice = devices.SelectedItem as Choice;
                bool lostDevice = false;
                updatingDevices = true;
                try
                {
                    devices.Items.Clear();
                    int selected = -1, defaultPlayback = -1, firstPlayback = -1;
                    foreach (object value in Items(message, "devices"))
                    {
                        Dictionary<string, object> item = value as Dictionary<string, object>;
                        if (item == null)
                            continue;
                        int id;
                        if (!Int32.TryParse(Value(item, "id"), out id))
                            continue;
                        string kind = Value(item, "kind");
                        string prefix = kind == "pc" ? "Computer audio · " : kind == "both" ? "Computer + microphone · " : "Microphone · ";
                        Choice choice = new Choice(kind, prefix + Value(item, "name"));
                        choice.DeviceId = id;
                        devices.Items.Add(choice);
                        if (kind == "pc" && firstPlayback < 0)
                            firstPlayback = devices.Items.Count - 1;
                        if (kind == "pc" && id == -2)
                            defaultPlayback = devices.Items.Count - 1;
                        if (oldDevice != null && id == oldDevice.DeviceId && choice.Code == oldDevice.Code && choice.Name == oldDevice.Name)
                            selected = devices.Items.Count - 1;
                    }

                    lostDevice = selected < 0 && oldDevice != null && audioWanted;
                    devices.SelectedIndex = selected >= 0 ? selected : defaultPlayback >= 0 ? defaultPlayback : firstPlayback;
                }
                finally
                {
                    updatingDevices = false;
                }

                if (lostDevice)
                {
                    StopAudio();
                    audioStateLabel.Text = "Audio stopped because the selected device changed.";
                }
                else if (!audioWanted && !lostDevice && devices.SelectedIndex >= 0)
                    audioStateLabel.Text = "Off. Choose computer audio for games, videos and voice chat.";
                else if (!audioWanted && devices.Items.Count > 0)
                    audioStateLabel.Text = "Off. Select a microphone or connect a playback device.";
                UpdateControls();
            }
            else if (type == "capture_state")
            {
                string state = Value(message, "state"), info = Value(message, "message");
                if (channel == "audio")
                {
                    audioStateLabel.Text = info != "" ? info : state == "active" ? "Listening. English captions follow each phrase." : state == "starting" ? "Opening audio device / loading model..." : "Audio is off.";
                    if (state == "error" || state == "stopped")
                    {
                        audioWanted = false;
                        ClearOverlayChannel("audio");
                        SetSwitch(audioToggle, false);
                    }
                }
                else if (channel == "screen")
                {
                    screenStateLabel.Text = info != "" ? info : state == "active" ? "Watching this area for changed text." : state == "starting" ? "Starting screen recognition..." : "Screen watching is off.";
                    if (state == "error" || state == "stopped")
                    {
                        screenWanted = false;
                        screenArmed = state == "error" && Flag(message, "retryable");
                        ClearOverlayChannel("screen");
                        SetSwitch(screenToggle, screenArmed);
                        if (screenArmed)
                            screenStateLabel.Text = "Display unavailable. Watching will retry.";
                    }
                }
                else if (channel == "screen_once" && (state == "error" || state == "stopped"))
                    oneShotPending = false;
                if (state == "stopped" || state == "error")
                    InvalidateRequests(channel);
                if (state == "error" && info != "")
                {
                    Append("CAPTURE", info);
                    SetStatus(info);
                }

                UpdateControls();
            }
            else if (type == "screen_clear" && channel == "screen")
            {
                ClearOverlayChannel("screen");
            }
            else if (type == "audio" || type == "screen" || type == "screen_once" || type == "result")
            {
                string audioSource = Value(message, "source");
                string label = type == "audio" ? (audioSource == "microphone" ? "MICROPHONE" : audioSource == "pc" ? "COMPUTER AUDIO" : "AUDIO")
                    : type == "screen" || type == "screen_once" ? "SCREEN" : "TEXT";
                string language = Value(message, "language").Trim().ToLowerInvariant();
                bool english = language == "en" || language == "eng" || language.StartsWith("en-", StringComparison.Ordinal)
                    || language.StartsWith("en_", StringComparison.Ordinal);
                bool outsideLiveSources = type == "audio" ? !PriorityProfile(language) && !speechSources.Contains(language)
                    : type != "result" && language != "mul" && !PriorityProfile(language) && !profiles.ContainsKey(language);
                bool ignored = Flag(message, "ignored") || english || outsideLiveSources || String.IsNullOrWhiteSpace(Value(message, "text"));
                if (type == "audio" && spokenQueue != null && spokenQueue.IsOwnVoice(Value(message, "original"), voiceClock.ElapsedMilliseconds)) ignored = true;
                // A one-shot read can finish after a newer watch frame. Its result still
                // belongs in the transcript; the active watcher owns the screen overlay.
                bool drivesScreenOverlay = type == "screen" || (type == "screen_once" && !screenWanted);
                if (language != "")
                    label += " / " + (type == "audio" && language == "zh" ? "Chinese" : ProfileName(language));
                if (!ignored)
                {
                    bool screen = type == "screen" || type == "screen_once";
                    try
                    {
                        if (type == "audio" || type == "result" || drivesScreenOverlay)
                            PresentVrCaption(type == "result" ? "text" : type, Value(message, "text"));
                        if (type == "audio") SpeakTranslation(Value(message, "text"));
                        if (drivesScreenOverlay)
                            screenCaptions.Present(Items(message, "regions"), Value(message, "text"), CaptureBounds(),
                                type == "screen_once" && !screenWanted, overlayToggle.Checked);
                        else if (type == "audio" && overlayToggle.Checked)
                            captionOverlay.PresentSpeech(Value(message, "text"), CaptureBounds());
                    }
                    finally
                    {
                        // Present immediately even when the transcript is long and Rich Edit must scroll.
                        if (!screen || !Flag(message, "layout_only"))
                            AddCaption(label, Value(message, "text"), Value(message, "original"));
                    }
                }
                else if (type == "result")
                {
                    ClearVrCaption("text");
                    SetStatus("No supported foreign text to translate.");
                }
                else if (drivesScreenOverlay)
                    ClearOverlayChannel("screen");
                if (type == "screen_once")
                {
                    oneShotPending = false;
                    onceSession = NewSession();
                    UpdateControls();
                    SetStatus(ignored ? "No supported foreign text found in this area." : "Read once complete.");
                }
            }
            else if (type == "error")
            {
                string info = Value(message, "message");
                Append("ERROR", info);
                SetStatus(info);
                string cmd = request == null ? "" : request.Command;
                if (cmd == "install_profile" || cmd == "install_all_profiles")
                    profileBusy = false;
                if (channel == "audio")
                {
                    audioWanted = false;
                    ClearOverlayChannel("audio");
                    SetSwitch(audioToggle, false);
                    audioStateLabel.Text = info;
                }

                if (channel == "screen")
                {
                    screenWanted = false;
                    screenArmed = false;
                    ClearOverlayChannel("screen");
                    SetSwitch(screenToggle, false);
                    screenStateLabel.Text = info;
                }

                if (channel == "screen_once")
                    oneShotPending = false;
                UpdateControls();
            }
            else if (type == "status")
                SetStatus(Value(message, "message"));
            else if (type == "ok")
            {
                string cmd = Value(message, "command");
                if (cmd == "" && request != null)
                    cmd = request.Command;
                if (cmd == "install_profile" || cmd == "install_all_profiles")
                    profileBusy = false;
                if (cmd == "install_profile" || cmd == "install_all_profiles" || cmd == "install_language" || cmd == "import_pack" || cmd == "download_speech" || cmd == "install_ocr")
                {
                    Send("status", null);
                    SetStatus(Value(message, "message"));
                }

                UpdateControls();
            }
        }

        private bool RuntimeReady()
        {
            string root = AppDomain.CurrentDomain.BaseDirectory, marker = Path.Combine(root, "runtime", "ready.txt");
            try
            {
                string version = File.Exists(marker) ? File.ReadAllText(marker).Trim() : "";
                return File.Exists(Path.Combine(root, "runtime", "python.exe")) && (version == "0.2" || version == "0.3" || version == "0.4" || version == "0.5");
            }
            catch
            {
                return false;
            }
        }

        private bool SetupRunning()
        {
            try
            {
                return installer != null && !installer.HasExited;
            }
            catch
            {
                return false;
            }
        }

        private void StartWorker()
        {
            if (closing || SetupRunning())
                return;
            if (worker != null)
            {
                if (!worker.HasExited)
                {
                    Send("status", null);
                    Send("devices", null);
                    return;
                }
                HandleWorkerExit(worker);
            }

            string root = AppDomain.CurrentDomain.BaseDirectory, script = Path.Combine(root, "backend", "worker.py");
            if (!RuntimeReady() || !File.Exists(script))
            {
                connected = false;
                SetStatus("Choose Install all four to set up the local engine and language models.");
                UpdateControls();
                return;
            }

            try
            {
                pending.Clear();
                stderrTail = "";
                ProcessStartInfo start = new ProcessStartInfo(Path.Combine(root, "runtime", "python.exe"), "-u \"" + script + "\"");
                start.WorkingDirectory = root;
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
                start.RedirectStandardInput = true;
                start.RedirectStandardOutput = true;
                start.RedirectStandardError = true;
                start.StandardOutputEncoding = Encoding.UTF8;
                start.StandardErrorEncoding = Encoding.UTF8;
                start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                start.EnvironmentVariables["PYTHONUTF8"] = "1";
                start.EnvironmentVariables["ORT_DISABLE_TELEMETRY"] = "1";
                worker = new Process();
                worker.StartInfo = start;
                worker.EnableRaisingEvents = true;
                Process started = worker;
                var parser = new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 };
                worker.OutputDataReceived += delegate (object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null)
                    {
                        // Stdout delivers lines serially. Decode the potentially large
                        // background patches here, keeping UI input and painting responsive.
                        Dictionary<string, object> msg;
                        try { msg = parser.DeserializeObject(e.Data) as Dictionary<string, object>; }
                        catch (Exception) { return; } // A malformed worker line must not terminate its reader.
                        if (msg == null) return;
                        Ui(delegate
                        {
                            if (worker != started)
                                return;
                            try
                            {
                                HandleMessage(msg);
                            }
                            catch
                            {
                            }
                        });
                    }
                };
                worker.ErrorDataReceived += delegate (object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null && worker == started)
                        lock (writeLock)
                        {
                            stderrTail += e.Data + Environment.NewLine;
                            if (stderrTail.Length > 4000)
                                stderrTail = stderrTail.Substring(stderrTail.Length - 4000);
                        }
                };
                worker.Exited += delegate
                {
                    Ui(delegate { HandleWorkerExit(started); });
                };
                worker.Start();
                inputWriter = new StreamWriter(worker.StandardInput.BaseStream, new UTF8Encoding(false));
                inputWriter.AutoFlush = true;
                worker.BeginOutputReadLine();
                worker.BeginErrorReadLine();
                SetStatus("Connecting to the local translation engine...");
                Send("status", null);
                Send("devices", null);
            }
            catch (Exception ex)
            {
                connected = false;
                DelayReconnect();
                if (worker != null)
                {
                    try { if (!worker.HasExited) worker.Kill(); }
                    catch (InvalidOperationException) {}
                    DisposeWorkerInput();
                    worker.Dispose();
                    worker = null;
                }
                SetStatus(ex.Message);
                Append("ENGINE", ex.Message);
                UpdateControls();
            }
        }

        private void HandleWorkerExit(Process ended)
        {
            if (worker != ended)
                return;
            // Process exit and pipe reads are delivered independently. Retire this
            // identity before a queued final line can update a new or absent engine.
            worker = null;
            connected = false;
            devicesReady = false;
            DisposeWorkerInput();
            ended.Dispose();
            pending.Clear();
            DelayReconnect();
            audioWanted = false;
            screenWanted = false;
            ClearOverlayChannel("");
            audioSession = NewSession();
            screenSession = NewSession();
            onceSession = NewSession();
            oneShotPending = false;
            profileBusy = false;
            SetSwitch(audioToggle, false);
            SetSwitch(screenToggle, screenArmed);
            audioStateLabel.Text = "Off. Local engine is unavailable.";
            screenStateLabel.Text = screenArmed ? "Waiting for the local engine to reconnect." : "Screen watching is paused.";
            UpdateControls();
            if (!SetupRunning())
            {
                SetStatus("Local engine stopped. Reconnecting automatically.");
                if (!String.IsNullOrWhiteSpace(stderrTail))
                    Append("ENGINE", stderrTail.Trim());
            }
        }

        private void DisposeWorkerInput()
        {
            StreamWriter writer = inputWriter;
            inputWriter = null;
            if (writer == null)
                return;
            try { writer.Dispose(); }
            catch (IOException) { }
            catch (ObjectDisposedException) { }
        }

        private bool Send(string command, Dictionary<string, object> args)
        {
            int id = 0;
            try
            {
                if (worker == null || worker.HasExited)
                {
                    SetStatus("Local engine is unavailable. Use setup or reconnect from Settings.");
                    return false;
                }

                if (args == null)
                    args = new Dictionary<string, object>();
                if (command == "status" && tesseractPath != null)
                    args["tesseract_path"] = tesseractPath.Text.Trim();
                id = Interlocked.Increment(ref requestId);
                args["command"] = command;
                args["id"] = id;
                PendingRequest request = new PendingRequest(command, Value(args, "session_id"), ChannelOf(command));
                if (command == "translate") { request.TypedText = Value(args, "text"); request.TypedSource = Value(args, "source"); }
                pending[id] = request;
                lock (writeLock)
                    inputWriter.WriteLine(json.Serialize(args));
                return true;
            }
            catch (Exception ex)
            {
                if (id != 0)
                    pending.Remove(id);
                SetStatus(ex.Message);
                return false;
            }
        }

        private void StartInstall(string command, string language)
        {
            if (audioWanted || screenWanted)
            {
                SetStatus("Turn listening and screen watching off before changing model files.");
                return;
            }

            if (SetupRunning() || profileBusy)
            {
                SetStatus("Setup is already running.");
                return;
            }

            if (!connected)
            {
                LaunchSetup(command, language);
                return;
            }

            if (Send(command, language == null ? null : Dict("language", language)))
            {
                profileBusy = true;
                SetStatus(command == "install_all_profiles" ? "Installing all four languages. Completed files are reused." : "Installing " + ProfileName(language) + ". Please wait for downloads to finish.");
                UpdateControls();
            }
        }

        private void SetupSelected(object sender, EventArgs e)
        {
            settingsTabs.SelectedIndex = 1;
            OpenSettings();
        }

        private void LaunchSetup(string afterCommand, string language, bool quality = false)
        {
            LaunchComponentSetup(afterCommand, language, quality ? ComponentSetup.Quality : ComponentSetup.Standard);
        }

        private static ProcessStartInfo SetupProcessInfo(ComponentSetup setup, string directory)
        {
            bool interactive = setup == ComponentSetup.KoreanDialogue;
            // Keep installation paths out of cmd.exe's command text, including literal percent signs.
            string args = interactive ? "/d /v:off /c call \".\\Install Korean dialogue.cmd\""
                : setup == ComponentSetup.Quality ? "/d /v:off /c call \".\\Install quality models.cmd\" --online --non-interactive"
                : "/d /v:off /c .\\Setup.cmd --non-interactive";
            return new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "cmd.exe"), args)
            {
                WorkingDirectory = directory, UseShellExecute = interactive, CreateNoWindow = !interactive,
                WindowStyle = ProcessWindowStyle.Normal, RedirectStandardOutput = !interactive, RedirectStandardError = !interactive
            };
        }

        private void LaunchComponentSetup(string afterCommand, string language, ComponentSetup setup)
        {
            bool interactive = setup == ComponentSetup.KoreanDialogue;
            if (SetupRunning() || (interactive && profileBusy))
            {
                SetStatus("Component setup is already running.");
                return;
            }

            if (audioWanted || screenWanted)
            {
                SetStatus("Pause screen watching and audio before installing components.");
                return;
            }

            string batch = interactive ? DialogueInstaller : setup == ComponentSetup.Quality ? "Install quality models.cmd" : "Setup.cmd";
            string setupFile = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, batch);
            if (!File.Exists(setupFile))
            {
                Append("SETUP", batch + " is missing. Extract the entire ZIP before opening this app.");
                return;
            }

            try
            {
                CloseWorker();
                pendingInstallCommand = afterCommand;
                pendingInstallLanguage = language;
                setupTail = "";
                if (installer != null)
                    installer.Dispose();
                installer = new Process();
                installer.StartInfo = SetupProcessInfo(setup, AppDomain.CurrentDomain.BaseDirectory);
                installer.EnableRaisingEvents = true;
                if (!interactive)
                {
                    installer.OutputDataReceived += SetupOutput;
                    installer.ErrorDataReceived += SetupOutput;
                }
                installer.Exited += delegate (object sender, EventArgs e)
                {
                    int exit = ((Process)sender).ExitCode;
                    Ui(delegate
                    {
                        if (exit == 0 && RuntimeReady())
                            StartWorker();
                        else
                        {
                            pendingInstallCommand = null;
                            pendingInstallLanguage = null;
                            Append("SETUP ERROR", interactive ? "Korean dialogue setup did not finish. Check its console for details." : "Setup did not finish.\n" + setupTail.Trim());
                            SetStatus(interactive ? "Korean dialogue setup did not finish." : "Setup failed. See its error in captions, then use Settings to retry.");
                            if (interactive && RuntimeReady())
                                StartWorker();
                        }

                        UpdateControls();
                    });
                };
                installer.Start();
                if (!interactive)
                {
                    installer.BeginOutputReadLine();
                    installer.BeginErrorReadLine();
                }
                SetStatus(interactive ? "Review the license and choose whether to install in the setup window."
                    : "Preparing local components. Keep the app open until the checks finish.");
                UpdateControls();
            }
            catch (Exception ex)
            {
                pendingInstallCommand = null;
                pendingInstallLanguage = null;
                Append("SETUP ERROR", ex.Message);
                SetStatus(ex.Message);
                UpdateControls();
            }
        }

        private void SetupOutput(object sender, DataReceivedEventArgs e)
        {
            if (String.IsNullOrWhiteSpace(e.Data))
                return;
            lock (writeLock)
            {
                setupTail += e.Data + Environment.NewLine;
                if (setupTail.Length > 7000)
                    setupTail = setupTail.Substring(setupTail.Length - 7000);
            }

            string line = e.Data.Trim();
            if (line.Length > 160)
                line = line.Substring(0, 160);
            Ui(delegate
            {
                SetStatus("Setup: " + line);
            });
        }

        private void AddCaption(string label, string text, string original)
        {
            if (String.IsNullOrWhiteSpace(text))
                return;
            TranscriptPosition position = new TranscriptPosition(output);
            int removed = 0;
            if (history.Count == 180)
            {
                // Rich Edit rejects selection deletions in a read-only window.
                // This block runs synchronously on the UI thread.
                output.ReadOnly = false;
                try
                {
                    removed = history[0].RenderedLength;
                    output.Select(0, removed);
                    output.SelectedText = "";
                }
                finally { output.ReadOnly = true; }
                history.RemoveAt(0);
            }
            CaptionEntry entry = new CaptionEntry(label, text.Trim(), original);
            history.Add(entry);
            output.Select(output.TextLength, 0);
            WriteCaption(entry);
            position.Restore(output, removed);
            emptyOutput.Visible = false;
            UpdateTranscriptTools();
        }

        private void Append(string label, string text)
        {
            AddCaption(label, text, "");
        }

        private void RenderCaptions()
        {
            TranscriptPosition position = new TranscriptPosition(output);
            int[] previousLengths = history.ConvertAll(delegate(CaptionEntry entry) { return entry.RenderedLength; }).ToArray();
            output.SuspendLayout();
            output.Clear();
            foreach (CaptionEntry entry in history)
                WriteCaption(entry);

            output.SelectionStart = output.TextLength;
            position.Reflow(previousLengths, history);
            position.Restore(output, 0);
            output.ResumeLayout();
            emptyOutput.Visible = history.Count == 0;
            UpdateTranscriptTools();
        }

        private void WriteCaption(CaptionEntry entry)
        {
            int start = output.TextLength;
            output.SelectionFont = labelFont;
            output.SelectionColor = entry.Label == "AUDIO" ? Color.FromArgb(65, 74, 142) : violet;
            if (entry.Label.Contains("ERROR")) output.SelectionColor = Color.FromArgb(159, 55, 53);
            output.AppendText(entry.Label);
            output.SelectionColor = secondaryInk;
            output.AppendText("    " + entry.Time + Environment.NewLine);
            output.SelectionFont = captionFont;
            output.SelectionColor = paperInk;
            output.AppendText(entry.Text + Environment.NewLine);
            if (showSource.Checked && !String.IsNullOrWhiteSpace(entry.Original))
            {
                output.SelectionFont = sourceFont;
                output.SelectionColor = secondaryInk;
                output.AppendText("Source: " + entry.Original.Trim() + Environment.NewLine);
            }
            output.AppendText(Environment.NewLine);
            entry.RenderedLength = output.TextLength - start;
        }

        private void SetStatus(string text)
        {
            if (status != null)
                status.Text = text;
        }

        private void Ui(MethodInvoker action)
        {
            if (closing || IsDisposed || !IsHandleCreated)
                return;
            try
            {
                BeginInvoke(action);
            }
            catch (InvalidOperationException)
            {
            }
        }

        private void CloseWorker()
        {
            Process current = worker;
            worker = null;
            connected = false;
            devicesReady = false;
            audioWanted = false;
            screenWanted = false;
            ClearOverlayChannel("");
            audioSession = NewSession();
            screenSession = NewSession();
            onceSession = NewSession();
            oneShotPending = false;
            try
            {
                if (current != null && !current.HasExited)
                {
                    try
                    {
                        lock (writeLock)
                            if (inputWriter != null)
                                inputWriter.WriteLine(json.Serialize(Dict("command", "shutdown", "id", -1)));
                    }
                    catch (IOException) { }
                    catch (ObjectDisposedException) { }
                    DisposeWorkerInput();
                    if (!current.WaitForExit(1500))
                        current.Kill();
                }
            }
            catch
            {
            }
            finally
            {
                DisposeWorkerInput();
                if (current != null)
                    current.Dispose();
            }

            if (audioToggle != null)
                SetSwitch(audioToggle, false);
            if (screenToggle != null)
                SetSwitch(screenToggle, screenArmed);
        }

        private void OnClosing(object sender, FormClosingEventArgs e)
        {
            if (SetupRunning())
            {
                e.Cancel = true;
                SetStatus("Component installation is still running. Keep the app open until it finishes.");
                return;
            }

            closing = true;
            CloseVrCaptions();
            readinessTimer.Stop();
            readinessTimer.Dispose();
            CloseWorker();
            voiceTimer.Dispose();
            captionOverlay.Dispose();
            screenCaptions.Dispose();
            if (settingsForm != null)
                settingsForm.Dispose();
            if (installer != null)
                installer.Dispose();
            captionFont.Dispose();
            labelFont.Dispose();
            sourceFont.Dispose();
        }
    }

    internal sealed class RegionPicker : Form
    {
        private Point anchor, current;
        private bool dragging;
        public Rectangle Selection { get; private set; }

        public RegionPicker()
        {
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            Bounds = SystemInformation.VirtualScreen;
            BackColor = Color.Black;
            Opacity = 0.42;
            TopMost = true;
            ShowInTaskbar = false;
            Cursor = Cursors.Cross;
            DoubleBuffered = true;
            KeyPreview = true;
            MouseDown += delegate (object sender, MouseEventArgs e)
            {
                if (e.Button == MouseButtons.Left)
                {
                    dragging = true;
                    anchor = e.Location;
                    current = e.Location;
                    Capture = true;
                    Invalidate();
                }
                else
                {
                    DialogResult = DialogResult.Cancel;
                    Close();
                }
            };
            MouseMove += delegate (object sender, MouseEventArgs e)
            {
                if (dragging)
                {
                    current = e.Location;
                    Invalidate();
                }
            };
            MouseUp += delegate (object sender, MouseEventArgs e)
            {
                if (!dragging)
                    return;
                dragging = false;
                Capture = false;
                current = e.Location;
                Rectangle local = Selected();
                if (local.Width < 20 || local.Height < 20)
                {
                    Invalidate();
                    return;
                }

                Selection = new Rectangle(PointToScreen(local.Location), local.Size);
                DialogResult = DialogResult.OK;
                Close();
            };
            KeyDown += delegate (object sender, KeyEventArgs e)
            {
                if (e.KeyCode == Keys.Escape)
                {
                    DialogResult = DialogResult.Cancel;
                    Close();
                }
            };
        }

        private Rectangle Selected()
        {
            return new Rectangle(Math.Min(anchor.X, current.X), Math.Min(anchor.Y, current.Y), Math.Abs(anchor.X - current.X), Math.Abs(anchor.Y - current.Y));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            using (Font font = new Font("Segoe UI", 18F, FontStyle.Bold))
            using (Brush brush = new SolidBrush(Color.White))
                e.Graphics.DrawString("Drag around the text. Esc to cancel.", font, brush, new PointF(32, 32));
            if (dragging)
                using (Pen pen = new Pen(Color.FromArgb(104, 219, 191), 3))
                    e.Graphics.DrawRectangle(pen, Selected());
        }
    }
}
