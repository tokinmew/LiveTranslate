using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class AudioSignalMeter : Control
    {
        int level;
        internal int Level { get { return level; } set { level = Math.Max(0, Math.Min(100, value)); Invalidate(); } }
        internal AudioSignalMeter()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
            AccessibleName = "Measured audio input level"; AccessibleRole = AccessibleRole.ProgressBar;
            BackColor = WindowTheme.Field; Size = new Size(220, 23);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(WindowTheme.HighContrast ? SystemColors.Window : BackColor);
            Rectangle bar = Rectangle.Inflate(ClientRectangle, -2, -3);
            using (var track = new SolidBrush(WindowTheme.HighContrast ? SystemColors.Control : WindowTheme.Border))
            using (var fill = new SolidBrush(WindowTheme.HighContrast ? SystemColors.Highlight : WindowTheme.Accent))
            {
                e.Graphics.FillRectangle(track, bar);
                if (Level > 0) { bar.Width = Math.Max(1, bar.Width * Level / 100); e.Graphics.FillRectangle(fill, bar); }
            }
        }
    }
    internal sealed partial class MainForm
    {
        sealed class InputSignal { internal int Level; internal long Seen; internal string Message; }
        readonly Dictionary<string, InputSignal> audioInputSignals = new Dictionary<string, InputSignal>();
        readonly Timer audioDiagnosticTimer = new Timer { Interval = 500 };
        AudioSignalMeter audioSignalMeter;
        Label audioSignalLabel, audioDecisionLabel, audioModelLabel;
        TextBox audioRecognizedText;
        Button smallSpeechButton;

        private string SpeechModelPreferenceFile
        { get { return Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "config", "speech-input.json"); } }

        private void LoadSpeechModelChoice()
        {
            try
            {
                if (!File.Exists(SpeechModelPreferenceFile) || new FileInfo(SpeechModelPreferenceFile).Length > 2048) return;
                var saved = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(SpeechModelPreferenceFile));
                string model = Value(saved, "model");
                if (audioModel.Items.Contains(model)) { audioModel.SelectedItem = model; speechModelChosen = true; }
            }
            catch (Exception) { }
        }

        private void RememberSpeechModelChoice()
        {
            speechModelChosen = true;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(SpeechModelPreferenceFile));
                File.WriteAllText(SpeechModelPreferenceFile, json.Serialize(Dict("model", Convert.ToString(audioModel.SelectedItem))));
            }
            catch (Exception) { SetStatus("Speech model selected for this session; the preference could not be saved."); }
        }

        private Control BuildAudioSignalDisplay()
        {
            TableLayoutPanel panel = Rows(23, 0);
            audioSignalMeter = new AudioSignalMeter { Dock = DockStyle.Fill, Margin = new Padding(0, 0, 0, 3) };
            audioSignalLabel = Note("Auto listen is off. The level shows measured input only.", secondaryInk);
            audioSignalLabel.Font = new Font(Font.FontFamily, 8.4F);
            audioSignalLabel.AccessibleRole = AccessibleRole.StatusBar;
            panel.Controls.Add(audioSignalMeter, 0, 0); panel.Controls.Add(audioSignalLabel, 0, 1);
            return panel;
        }

        private Control BuildAudioRecognitionDisplay()
        {
            ModernCard card = LightCard(paper, new Padding(13, 7, 13, 9));
            card.Margin = new Padding(0, 0, 0, 10);
            TableLayoutPanel rows = Rows(29, 38, 0);
            TableLayoutPanel heading = Columns(0, 203);
            audioModelLabel = Note("Speech model: base", paperInk);
            audioModelLabel.Font = new Font(Font.FontFamily, 10F, FontStyle.Bold);
            smallSpeechButton = SessionButton("Install Small (~464 MiB)", UseOrInstallSmallSpeech, false);
            smallSpeechButton.Font = new Font(Font.FontFamily, 8.3F);
            heading.Controls.Add(audioModelLabel, 0, 0); heading.Controls.Add(smallSpeechButton, 1, 0);
            rows.Controls.Add(heading, 0, 0);
            audioDecisionLabel = Note("Recognition check: waiting for an audio phrase. Details do not become captions.", secondaryInk);
            audioDecisionLabel.Font = new Font(Font.FontFamily, 9F);
            audioDecisionLabel.AccessibleRole = AccessibleRole.StatusBar;
            rows.Controls.Add(audioDecisionLabel, 0, 1);
            audioRecognizedText = Entry(""); audioRecognizedText.Multiline = true; audioRecognizedText.ReadOnly = true;
            audioRecognizedText.ScrollBars = ScrollBars.Vertical;
            audioRecognizedText.Font = new Font(Font.FontFamily, 9F);
            audioRecognizedText.AccessibleName = "Last recognised source, diagnostic only and possibly incorrect";
            rows.Controls.Add(audioRecognizedText, 0, 2);
            card.Controls.Add(rows);
            audioDiagnosticTimer.Tick += delegate { RefreshMeasuredAudioLevel(); };
            Disposed += delegate { audioDiagnosticTimer.Dispose(); };
            return card;
        }

        private static double AudioNumber(Dictionary<string, object> message, string name, double fallback)
        {
            object value;
            try
            {
                double number = message.TryGetValue(name, out value) ? Convert.ToDouble(value, CultureInfo.InvariantCulture) : fallback;
                return Double.IsNaN(number) || Double.IsInfinity(number) ? fallback : number;
            }
            catch (Exception) { return fallback; }
        }

        private void HandleAudioDiagnostic(Dictionary<string, object> message)
        {
            if (!audioWanted || !CurrentSession("audio", Value(message, "session_id"))) return;
            string stage = Value(message, "stage");
            if (stage == "signal")
            {
                string key = Value(message, "source") + ":" + Value(message, "endpoint");
                if (key.Length > 100 || (audioInputSignals.Count >= 8 && !audioInputSignals.ContainsKey(key))) return;
                audioInputSignals[key] = new InputSignal { Level = (int)Math.Max(0, Math.Min(100, AudioNumber(message, "level", 0))),
                    Seen = voiceClock.ElapsedMilliseconds, Message = Value(message, "message") };
                if (!audioDiagnosticTimer.Enabled) audioDiagnosticTimer.Start();
                RefreshMeasuredAudioLevel();
            }
            else if (stage == "recognition")
            {
                string language = Value(message, "language");
                string label = language == "" ? "" : language == "en" ? "English" : ProfileName(language);
                if (message.ContainsKey("probability")) label += " (" + Math.Round(Math.Max(0, Math.Min(1, AudioNumber(message, "probability", 0))) * 100) + "% language confidence)";
                string detail = Value(message, "message");
                if (detail.Length > 420) detail = detail.Substring(0, 420);
                audioDecisionLabel.Text = (label == "" ? "Recognition check: " : label + ": ") + detail;
                string recognized = Value(message, "recognized");
                audioRecognizedText.Text = recognized.Length > 512 ? recognized.Substring(0, 512) : recognized;
            }
        }

        private void RefreshMeasuredAudioLevel()
        {
            if (audioSignalMeter == null || IsDisposed || closing) return;
            if (!audioWanted) { ResetAudioDiagnostics(); return; }
            long now = voiceClock.ElapsedMilliseconds;
            InputSignal strongest = null;
            foreach (InputSignal inputSignal in audioInputSignals.Values)
                if (now - inputSignal.Seen <= 2500 && (strongest == null || inputSignal.Level > strongest.Level)) strongest = inputSignal;
            audioSignalMeter.Level = strongest == null ? 0 : strongest.Level;
            audioSignalLabel.Text = strongest == null ? "Waiting for measured audio from the selected input…" : strongest.Message;
        }

        private void ResetAudioDiagnostics()
        {
            ClearCaptureError("audio");
            audioInputSignals.Clear(); audioDiagnosticTimer.Stop();
            if (audioSignalMeter != null) audioSignalMeter.Level = 0;
            if (audioSignalLabel != null) audioSignalLabel.Text = audioWanted ? "Waiting for measured audio from the selected input…" : "Auto listen is off.";
            if (audioDecisionLabel != null) audioDecisionLabel.Text = "Recognition check: no new phrase yet.";
            if (audioRecognizedText != null) audioRecognizedText.Clear();
        }

        private void RefreshAudioDiagnosticControls()
        {
            if (audioModelLabel == null || audioModel == null) return;
            string model = Convert.ToString(audioModel.SelectedItem);
            audioModelLabel.Text = "Speech model: " + model + (speechModelChosen ? " (selected)" : "");
            bool present = speechModels.Contains("small");
            smallSpeechButton.Text = present ? model == "small" ? "Small model selected" : "Use Small model" : "Install Small (~464 MiB)";
            smallSpeechButton.Enabled = !closing && !SetupRunning() && !profileBusy && (present ? model != "small" : !audioWanted && !screenWanted);
            if (!audioWanted && audioInputSignals.Count != 0) ResetAudioDiagnostics();
        }

        private void UseOrInstallSmallSpeech(object sender, EventArgs args)
        {
            if (closing || SetupRunning() || profileBusy) return;
            if (speechModels.Contains("small"))
            {
                audioModel.SelectedItem = "small";
                RememberSpeechModelChoice();
                if (audioWanted) RestartAudio();
                RefreshAudioDiagnosticControls();
                SetStatus("Small speech model selected. The next phrase uses it.");
            }
            else LaunchComponentSetup(null, null, ComponentSetup.SmallSpeech);
        }
    }
}
