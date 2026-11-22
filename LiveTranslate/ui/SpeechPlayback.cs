using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class VoiceOptions
    {
        public bool Enabled { get; set; }
        public string Voice { get; set; }
        public string Output { get; set; }
        public int Rate { get; set; }
        public int Volume { get; set; }
        public VoiceOptions() { Voice = Output = ""; Volume = 80; }
    }

    internal interface ISpokenOutput : IDisposable
    {
        bool Finished { get; }
        void Say(string text);
        void Stop();
    }

    // The WinForms thread owns both the SAPI object and its asynchronous speech queue.
    internal sealed class WindowsVoice : ISpokenOutput
    {
        object speaker;
        static object Member(object target, string name, BindingFlags flags, params object[] arguments)
        {
            return target.GetType().InvokeMember(name, flags, null, target, arguments, CultureInfo.InvariantCulture);
        }
        static object Call(object target, string name, params object[] args) { return Member(target, name, BindingFlags.InvokeMethod, args); }
        static void Release(object value) { if (value != null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value); }
        internal WindowsVoice()
        {
            Type type = Type.GetTypeFromProgID("SAPI.SpVoice", true);
            speaker = Activator.CreateInstance(type);
        }

        // SpObjectTokens exposes indexed items and localized device names without extra assemblies.
        internal List<Choice> Tokens(bool voices, string select)
        {
            var choices = new List<Choice>();
            object tokens;
            try { tokens = Call(speaker, voices ? "GetVoices" : "GetAudioOutputs", "", ""); }
            catch (TargetInvocationException e)
            {
                // Windows can lack a per-user token category even when machine-wide voices exist.
                COMException reason = e.GetBaseException() as COMException;
                if (reason == null || reason.ErrorCode != unchecked((int)0x80045039)) throw;
                object category = Activator.CreateInstance(Type.GetTypeFromProgID("SAPI.SpObjectTokenCategory", true));
                try
                {
                    Call(category, "SetId", @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\" + (voices ? "Voices" : "AudioOutput"), false);
                    tokens = Call(category, "EnumerateTokens", "", "");
                }
                finally { Release(category); }
            }
            bool selected = false;
            try
            {
                int count = Convert.ToInt32(Member(tokens, "Count", BindingFlags.GetProperty));
                for (int i = 0; i < count; i++)
                {
                    object token = Member(tokens, "Item", BindingFlags.InvokeMethod | BindingFlags.GetProperty, i);
                    try
                    {
                        if (voices)
                        {
                            string languages = Convert.ToString(Call(token, "GetAttribute", "Language"));
                            bool english = false;
                            foreach (string value in languages.Split(';'))
                            {
                                int lcid;
                                if (Int32.TryParse(value.Trim(), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out lcid) &&
                                    (lcid & 0x3ff) == 9) english = true;
                            }
                            if (!english) continue;
                        }
                        string id = Convert.ToString(Member(token, "Id", BindingFlags.GetProperty));
                        choices.Add(new Choice(id, Convert.ToString(Call(token, "GetDescription", 0))));
                        if (!selected && select != null && ((voices && select == "") ||
                            String.Equals(select, id, StringComparison.OrdinalIgnoreCase)))
                        {
                            Member(speaker, voices ? "Voice" : "AudioOutput", BindingFlags.SetProperty, token);
                            selected = true;
                        }
                    }
                    finally { Release(token); }
                }
            }
            finally { Release(tokens); }
            if (select != null && !selected && (voices || select.Length > 0))
                throw new InvalidOperationException(voices ? "Select an installed English voice in Spoken English settings." :
                    "The selected playback device is unavailable. Choose a connected output in Spoken English settings.");
            return choices;
        }

        internal void Configure(VoiceOptions prefs)
        {
            Tokens(true, prefs.Voice ?? "");
            if (!String.IsNullOrEmpty(prefs.Output)) Tokens(false, prefs.Output);
            Member(speaker, "Rate", BindingFlags.SetProperty, prefs.Rate);
            Member(speaker, "Volume", BindingFlags.SetProperty, prefs.Volume);
        }

        public bool Finished { get { return Convert.ToBoolean(Call(speaker, "WaitUntilDone", 0)); } }
        public void Say(string text) { Call(speaker, "Speak", text, 1 | 16); } // async, plain text
        public void Stop() { Call(speaker, "Speak", "", 1 | 2 | 16); } // also purge anything already submitted
        public void Dispose() { if (speaker != null) { Release(speaker); speaker = null; } }
    }

    internal sealed class SpokenQueue : IDisposable
    {
        readonly Queue<KeyValuePair<long, string>> pending = new Queue<KeyValuePair<long, string>>();
        readonly Queue<KeyValuePair<long, string>> recent = new Queue<KeyValuePair<long, string>>();
        readonly ISpokenOutput output;
        string current;
        internal SpokenQueue(ISpokenOutput output) { this.output = output; }
        internal bool Busy { get { return current != null || pending.Count > 0; } }
        static string Words(string value)
        {
            if (String.IsNullOrEmpty(value)) return "";
            var s = new StringBuilder();
            foreach (char c in value) if (Char.IsLetterOrDigit(c)) s.Append(Char.ToLowerInvariant(c));
            return s.ToString();
        }
        internal bool IsOwnVoice(string original, long now)
        {
            string words = Words(original);
            if (words.Length == 0) return false;
            if (current != null && words == Words(current)) return true;
            while (recent.Count > 0 && recent.Peek().Key + 3000 < now) recent.Dequeue();
            foreach (var item in recent) if (item.Value == words) return true;
            return false;
        }
        internal void Add(string text, long now)
        {
            if (String.IsNullOrWhiteSpace(text) || text.Length > 2000) return;
            if (pending.Count == 3) pending.Dequeue();
            pending.Enqueue(new KeyValuePair<long, string>(now, text));
            Tick(now);
        }
        internal void Tick(long now)
        {
            if (current != null)
            {
                if (!output.Finished) return;
                if (recent.Count == 4) recent.Dequeue();
                recent.Enqueue(new KeyValuePair<long, string>(now, Words(current)));
                current = null;
            }
            while (pending.Count > 0)
            {
                var next = pending.Dequeue();
                if (now - next.Key > 8000) continue;
                current = next.Value;
                output.Say(current);
                break;
            }
        }
        public void Dispose()
        {
            pending.Clear(); recent.Clear();
            try { if (current != null) output.Stop(); }
            finally { current = null; output.Dispose(); }
        }
    }

    internal sealed partial class MainForm
    {
        CheckBox speakEnabled;
        ComboBox spokenVoice, spokenDevice;
        NumericUpDown spokenRate, spokenVolume;
        Label voiceStatus;
        TabPage spokenTab;
        bool loadingVoice;
        VoiceOptions voicePrefs;
        SpokenQueue spokenQueue;
        readonly Stopwatch voiceClock = Stopwatch.StartNew();
        readonly Timer voiceTimer = new Timer { Interval = 120 };
        private static string VoicePreferenceFile { get { return Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "data", "spoken-english.json"); } }

        private void BuildSpokenTab()
        {
            voicePrefs = new VoiceOptions();
            try
            {
                string path = VoicePreferenceFile;
                if (File.Exists(path) && new FileInfo(path).Length < 16384)
                    voicePrefs = json.Deserialize<VoiceOptions>(File.ReadAllText(path)) ?? new VoiceOptions();
            }
            catch (Exception) { }
            spokenTab = new TabPage("Spoken English") { BackColor = surface, Padding = new Padding(13), AutoScroll = true };
            var controls = new TableLayoutPanel { Dock = DockStyle.Top, Height = 310, RowCount = 7, ColumnCount = 2 };
            controls.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 145));
            controls.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            for (int i = 0; i < 6; i++) controls.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
            controls.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            speakEnabled = new CheckBox { Text = "Read voice translations aloud", AutoSize = true, ForeColor = ink, Checked = voicePrefs.Enabled };
            controls.Controls.Add(speakEnabled, 0, 0); controls.SetColumnSpan(speakEnabled, 2);
            spokenVoice = Combo(); spokenDevice = Combo();
            AddSetting(controls, 1, "English voice", spokenVoice);
            AddSetting(controls, 2, "Playback device", spokenDevice);
            spokenRate = new NumericUpDown { Minimum = -10, Maximum = 10, Value = Math.Min(10, Math.Max(-10, voicePrefs.Rate)), Width = 100 };
            spokenVolume = new NumericUpDown { Minimum = 0, Maximum = 100, Value = Math.Min(100, Math.Max(0, voicePrefs.Volume)), Width = 100 };
            voicePrefs.Rate = (int)spokenRate.Value; voicePrefs.Volume = (int)spokenVolume.Value;
            AddSetting(controls, 3, "Speed (0 = normal)", spokenRate);
            AddSetting(controls, 4, "Voice volume (%)", spokenVolume);
            Button refresh = MakeButton("Refresh devices", delegate { RefreshVoiceOptions(); }, false);
            refresh.Width = 145; controls.Controls.Add(refresh, 1, 5);
            voiceStatus = Note("Listen to translated voices from Auto listen. Your game and call keep their original sound.", muted);
            controls.Controls.Add(voiceStatus, 0, 6); controls.SetColumnSpan(voiceStatus, 2);
            spokenTab.Controls.Add(controls); settingsTabs.TabPages.Add(spokenTab);
            settingsTabs.SelectedIndexChanged += delegate { if (settingsTabs.SelectedTab == spokenTab) RefreshVoiceOptions(); };
            speakEnabled.CheckedChanged += delegate { if (!loadingVoice) ChangeVoiceSettings(); };
            spokenDevice.SelectionChangeCommitted += delegate { ChangeVoiceSettings(); };
            spokenVoice.SelectionChangeCommitted += delegate { ChangeVoiceSettings(); };
            spokenRate.ValueChanged += delegate { ChangeVoiceSettings(); };
            spokenVolume.ValueChanged += delegate { ChangeVoiceSettings(); };
            voiceTimer.Tick += delegate
            {
                try
                {
                    if (spokenQueue != null) spokenQueue.Tick(voiceClock.ElapsedMilliseconds);
                    if (spokenQueue == null || !spokenQueue.Busy) voiceTimer.Stop();
                }
                catch (Exception e) { VoiceFailed(e); }
            };
        }
        private void RefreshVoiceOptions()
        {
            loadingVoice = true;
            try
            {
                using (var sapi = new WindowsVoice())
                {
                    List<Choice> voices = sapi.Tokens(true, null), outputs = sapi.Tokens(false, null);
                    FillVoiceChoice(spokenVoice, voices, voicePrefs.Voice, "First installed English voice");
                    FillVoiceChoice(spokenDevice, outputs, voicePrefs.Output, "Windows default playback");
                    speakEnabled.Enabled = voices.Count > 0 || speakEnabled.Checked;
                    voiceStatus.Text = voices.Count == 0 ? "Install an English speech voice in Windows language settings and refresh." :
                        "Changes take effect immediately. Turn reading off to stop the voice and clear queued translations.";
                }
            }
            catch (Exception e) { voiceStatus.Text = "Windows voice service unavailable. " + e.GetBaseException().Message; }
            finally { loadingVoice = false; }
        }
        static void FillVoiceChoice(ComboBox box, List<Choice> options, string saved, string defaultLabel)
        {
            box.Items.Clear(); box.Items.Add(new Choice("", defaultLabel)); box.SelectedIndex = 0;
            foreach (Choice c in options)
            {
                int i = box.Items.Add(c);
                if (String.Equals(c.Code, saved, StringComparison.OrdinalIgnoreCase)) box.SelectedIndex = i;
            }
            if (!String.IsNullOrEmpty(saved) && box.SelectedIndex == 0)
                box.SelectedIndex = box.Items.Add(new Choice(saved, "Previously selected (unavailable)"));
        }
        private void SaveVoiceSettings()
        {
            string path = VoicePreferenceFile;
            string temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                File.WriteAllText(temp, json.Serialize(voicePrefs));
                if (File.Exists(path)) File.Replace(temp, path, null); else File.Move(temp, path);
            }
            catch (Exception e) { voiceStatus.Text = "Changes apply to this session. Could not save settings: " + e.Message; }
            finally { try { if (File.Exists(temp)) File.Delete(temp); } catch (IOException) { } }
        }
        private void ChangeVoiceSettings()
        {
            if (loadingVoice) return;
            StopSpoken();
            voicePrefs.Enabled = speakEnabled.Checked;
            if (spokenVoice.SelectedItem != null) voicePrefs.Voice = ((Choice)spokenVoice.SelectedItem).Code;
            if (spokenDevice.SelectedItem != null) voicePrefs.Output = ((Choice)spokenDevice.SelectedItem).Code;
            voicePrefs.Rate = (int)spokenRate.Value; voicePrefs.Volume = (int)spokenVolume.Value;
            voiceStatus.Text = voicePrefs.Enabled ? "On. The next translated voice caption will play here." : "Spoken English is off.";
            SaveVoiceSettings();
        }
        private void SpeakTranslation(string text)
        {
            if (!voicePrefs.Enabled || closing) return;
            try
            {
                if (spokenQueue == null)
                {
                    var sapi = new WindowsVoice();
                    try { sapi.Configure(voicePrefs); spokenQueue = new SpokenQueue(sapi); }
                    catch { sapi.Dispose(); throw; }
                }
                spokenQueue.Add(text, voiceClock.ElapsedMilliseconds);
                if (spokenQueue.Busy) voiceTimer.Start();
            }
            catch (Exception e) { VoiceFailed(e); }
        }
        private void StopSpoken()
        {
            voiceTimer.Stop();
            if (spokenQueue == null) return;
            try { spokenQueue.Dispose(); } catch (Exception) { } finally { spokenQueue = null; }
        }
        private void VoiceFailed(Exception e)
        {
            StopSpoken();
            loadingVoice = true;
            try { speakEnabled.Checked = voicePrefs.Enabled = false; } finally { loadingVoice = false; }
            string msg = "Spoken English stopped. " + e.GetBaseException().Message;
            voiceStatus.Text = msg; SetStatus(msg); SaveVoiceSettings();
        }
    }
}
