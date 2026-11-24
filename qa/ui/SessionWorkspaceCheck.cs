using System;
using System.Collections;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using LiveTranslate;

internal static class SessionWorkspaceCheck
{
    const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;
    [DllImport("user32.dll", SetLastError = true)] static extern bool PrintWindow(IntPtr window, IntPtr dc, uint flags);
    static int passed;
    static T Field<T>(MainForm form, string name) { return (T)typeof(MainForm).GetField(name, Instance).GetValue(form); }
    static void Put(MainForm form, string name, object value) { typeof(MainForm).GetField(name, Instance).SetValue(form, value); }
    static void Call(MainForm form, string name, params object[] args) { typeof(MainForm).GetMethod(name, Instance).Invoke(form, args); }
    static void Check(bool value, string detail)
    {
        if (!value) throw new InvalidOperationException(detail);
        Console.WriteLine("PASS " + detail);
        passed++;
    }
    static void IsolateStartup(MainForm form)
    {
        EventHandlerList events = (EventHandlerList)typeof(Component).GetProperty("Events", Instance).GetValue(form, null);
        foreach (string name in new[] { "EVENT_LOAD", "EVENT_SHOWN" })
        {
            object key = typeof(Form).GetField(name, Static).GetValue(null);
            if (events[key] != null) events.RemoveHandler(key, events[key]);
        }
    }
    static void Snapshot(MainForm form, string directory, string name)
    {
        form.PerformLayout(); Application.DoEvents(); form.Update();
        using (Bitmap bitmap = new Bitmap(form.Width, form.Height))
        using (Graphics graphics = Graphics.FromImage(bitmap))
        {
            IntPtr dc = graphics.GetHdc();
            try { if (!PrintWindow(form.Handle, dc, 2)) throw new System.ComponentModel.Win32Exception(); }
            finally { graphics.ReleaseHdc(dc); }
            bitmap.Save(Path.Combine(directory, name + ".png"), ImageFormat.Png);
        }
    }
    [STAThread] static int Main(string[] args)
    {
        string directory = Path.GetFullPath(args.Length == 0 ? Path.Combine(Path.GetTempPath(), "LiveTranslate-session-ui") : args[0]);
        Directory.CreateDirectory(directory);
        Application.EnableVisualStyles();
        using (MainForm form = new MainForm())
        {
            IsolateStartup(form);
            form.Opacity = 0;
            form.Show();
            form.Size = new Size(1280, 820);
            Application.DoEvents();
            RichTextBox output = Field<RichTextBox>(form, "output");
            TextBox input = Field<TextBox>(form, "input");
            ComboBox devices = Field<ComboBox>(form, "devices");
            ModernSwitch audio = Field<ModernSwitch>(form, "audioToggle");
            Check(Field<object>(form, "worker") == null, "Constructing pages and showing the isolated fixture starts no capture worker");
            Check(output.TextLength == 0 && !Field<Button>(form, "sessionSaveButton").Enabled, "First launch has no fabricated captions and no transcript to save");
            devices.Items.Add(new Choice("pc", "Computer audio · Fixture playback"));
            devices.Items.Add(new Choice("microphone", "Microphone · Fixture microphone"));
            devices.SelectedIndex = 0;
            devices.SelectedIndex = 1;
            Check(!Field<bool>(form, "audioWanted") && Field<Button>(form, "sessionAudioSummary").Text.Contains("Fixture microphone") &&
                Field<Label>(form, "sessionAudioSourceTitle").Text == "Microphone" &&
                Field<Button>(form, "sessionMicMode").BackColor == Field<Color>(form, "accent"),
                "Changing the native device dropdown while stopped refreshes source summary and capture-mode state");
            devices.Items.Add(new Choice("pc", "Computer audio · Fixture secondary playback"));
            devices.Enabled = true;
            devices.SelectedIndex = devices.Items.Count - 1;
            int secondaryDevice = devices.SelectedIndex;
            Call(form, "SelectSessionAudioKind", "pc");
            Check(devices.SelectedIndex == secondaryDevice && Field<Button>(form, "sessionAudioSummary").Text.Contains("secondary playback"),
                "Clicking the active capture mode retains the exact selected secondary device");
            for (int index = 0; index < 32; index++)
                Call(form, "AddCaption", "TEXT / Japanese", "Fixture " + index + ": please meet at the east entrance.", "東口で待ち合わせましょう。");
            int marker = output.Text.IndexOf("Fixture 5:", StringComparison.Ordinal);
            output.Select(marker, "Fixture 5:".Length);
            output.ScrollToCaret();
            string selected = output.SelectedText;
            form.ShowSessionPage("history");
            Check(Object.ReferenceEquals(output, Field<RichTextBox>(form, "output")), "History uses the same canonical transcript control");
            Check(output.SelectedText == selected, "Moving the transcript to history preserves the reader selection");
            Call(form, "AddCaption", "TEXT / Japanese", "Fixture next: another caption arrived.", "次の字幕です。");
            Check(output.SelectedText == selected, "A new arrival on history preserves selection and existing history");
            form.ShowSessionPage("audio");
            Check(Object.ReferenceEquals(devices, Field<ComboBox>(form, "devices")) && Object.ReferenceEquals(audio, Field<ModernSwitch>(form, "audioToggle")),
                "Audio setup uses canonical device and input controls");
            form.ShowSessionPage("settings");
            form.ShowSessionPage("live");
            Check(Object.ReferenceEquals(input, Field<TextBox>(form, "input")) && output.SelectedText == selected,
                "Page navigation retains typed-input control and transcript reading position");
            Check(Field<object>(form, "worker") == null, "Navigation does not start a worker or restart capture");
            int count = Field<IList>(form, "history").Count;
            Put(form, "screenArmed", true); Put(form, "screenWanted", true); Put(form, "audioWanted", true); Put(form, "oneShotPending", true);
            Put(form, "screenSession", "before-pause-screen"); Put(form, "audioSession", "before-pause-audio"); Put(form, "onceSession", "before-pause-once");
            form.ToggleSessionPause();
            Check(form.SessionPaused && !Field<bool>(form, "screenArmed") && !Field<bool>(form, "screenWanted") && !Field<bool>(form, "audioWanted") && !Field<bool>(form, "oneShotPending"),
                "Pause cancels screen, audio and pending one-shot work");
            Check(Field<string>(form, "screenSession") != "before-pause-screen" && Field<string>(form, "audioSession") != "before-pause-audio" && Field<string>(form, "onceSession") != "before-pause-once",
                "Pause invalidates stale session results");
            Check(Field<IList>(form, "history").Count == count && form.SessionPauseLabel == "Resume translation", "Pause keeps session history and exposes resume");
            Put(form, "oneShotPending", true);
            form.RefreshSessionUi();
            Check(form.SessionPaused && form.SessionStatusText == "Reading screen" && form.SessionPauseLabel == "Resume translation",
                "A manual screen read reports active work without resuming paused capture");
            Put(form, "oneShotPending", false);
            form.RefreshSessionUi();
            Check(form.SessionPaused && form.SessionStatusText == "Paused", "Completing a manual screen read returns to the paused state");
            form.ToggleSessionPause();
            Check(!form.SessionPaused && Field<bool>(form, "screenArmed"), "Resume restores screen intent while unavailable inputs remain safely stopped");
            Check(Field<Label>(form, "status").Text.StartsWith("Audio could not resume.", StringComparison.Ordinal),
                "Unavailable audio remains actionable instead of falsely reporting a resumed session");
            form.EndSession();
            Check(!form.SessionPaused && !Field<bool>(form, "screenArmed") && !Field<bool>(form, "screenWanted") && !Field<bool>(form, "audioWanted") && Field<IList>(form, "history").Count == count,
                "End session stops capture and keeps history without saving it");
            foreach (string page in new[] { "live", "history", "audio", "settings" })
            {
                form.ShowSessionPage(page);
                Check(Field<Label>(form, "sessionPageTitle").Text.Length > 0, "Page has an accessible heading: " + page);
                Snapshot(form, directory, "session-" + page + "-1280");
            }
            form.ShowSessionPage("live");
            foreach (string button in new[] { "sessionPauseButton", "sessionEndButton", "sessionCaptionButton" })
            {
                Button control = Field<Button>(form, button);
                Check(control.Visible && control.Width >= 100 && control.Height >= 30 && control.Parent.ClientRectangle.IntersectsWith(control.Bounds),
                    "Live action remains visible with usable bounds: " + button);
            }
            form.Size = new Size(900, 620);
            foreach (string page in new[] { "live", "history", "audio", "settings" })
            {
                form.ShowSessionPage(page);
                Snapshot(form, directory, "session-" + page + "-minimum");
            }
            form.ShowSessionPage("live");
            Call(form, "ToggleSessionDetails");
            Check(Field<Control>(form, "sessionCaptureDetails").Visible, "Screen and language details remain available on Live");
            Snapshot(form, directory, "session-live-details-minimum");
            Check(Field<object>(form, "worker") == null, "All native page tests leave capture inputs closed");
            Console.WriteLine(passed + " session workspace checks passed; synthetic captions only.");
            form.Hide();
        }
        return 0;
    }
}
