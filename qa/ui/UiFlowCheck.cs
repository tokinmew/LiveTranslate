using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Reflection;
using System.Windows.Forms;
using LiveTranslate;

// Isolated application windows only. Startup capture, network, model installers,
// clipboard actions and user files are not exercised by this lifecycle fixture.
internal static class UiFlowCheck
{
    const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;
    static int passed;
    static Exception uiError;
    static T Field<T>(MainForm app, string name) { return (T)typeof(MainForm).GetField(name, Instance).GetValue(app); }
    static void Put(MainForm app, string name, object value) { typeof(MainForm).GetField(name, Instance).SetValue(app, value); }
    static void Call(MainForm app, string name, params object[] args) { typeof(MainForm).GetMethod(name, Instance).Invoke(app, args); }
    static void Check(bool value, string detail)
    {
        if (!value) throw new InvalidOperationException(detail);
        passed++;
        Console.WriteLine("PASS " + detail);
    }
    static void Pump()
    {
        Application.DoEvents();
        if (uiError != null) throw new InvalidOperationException("Unhandled UI event exception", uiError);
    }
    static void Isolate(Form form)
    {
        var events = (EventHandlerList)typeof(Component).GetProperty("Events", Instance).GetValue(form, null);
        foreach (string name in new[] { "EVENT_LOAD", "EVENT_SHOWN" })
        {
            object key = typeof(Form).GetField(name, Static).GetValue(null);
            if (events[key] != null) events.RemoveHandler(key, events[key]);
        }
        form.ShowInTaskbar = false;
        form.StartPosition = FormStartPosition.Manual;
        form.Location = new Point(SystemInformation.VirtualScreen.Right + 200, 0);
    }

    static void SettingsFlows(MainForm app, Form settings)
    {
        Call(app, "SelectProfile", "other");
        Call(app, "OpenSettings"); Pump();
        Check(settings.Visible && !settings.IsDisposed, "Settings opens as a persistent app window");
        TextBox speech = Field<TextBox>(app, "audioLanguage"), ocr = Field<TextBox>(app, "ocrLanguage");
        speech.Text = "de"; ocr.Text = "deu";
        string session = Field<string>(app, "screenSession");
        settings.WindowState = FormWindowState.Minimized; Pump();
        Check(settings.WindowState == FormWindowState.Minimized, "Settings fixture reaches its real minimized state");
        Call(app, "OpenSettings"); Pump();
        Check(settings.WindowState == FormWindowState.Normal && settings.Visible, "Reopening minimized Settings restores the window");
        Check(speech.Text == "de" && ocr.Text == "deu", "Restoring Settings preserves uncommitted recognition edits");
        Check(Field<string>(app, "screenSession") == session, "Restoring Settings does not apply edits or restart capture");
        settings.Close(); Pump();
        Check(!settings.Visible && !settings.IsDisposed, "Closing Settings hides it rather than disposing shared controls");
        Check(Field<Dictionary<string, string>>(app, "speechOverrides")["other"] == "de" &&
            Field<Dictionary<string, string>>(app, "ocrOverrides")["other"] == "deu", "Closing Settings applies the pending custom language values");
        Call(app, "OpenSettings"); Pump();
        Check(Object.ReferenceEquals(settings, Field<Form>(app, "settingsForm")) && speech.Text == "de" && ocr.Text == "deu",
            "Reopening Settings reuses the live window and applied edits");
        session = Field<string>(app, "screenSession");
        settings.Close(); Pump();
        Check(Field<string>(app, "screenSession") == session, "Closing unchanged Settings leaves the capture session alone");
        for (int round = 0; round < 4; round++)
        {
            Call(app, "OpenSettings"); Pump();
            settings.WindowState = FormWindowState.Minimized; Pump();
            Call(app, "OpenSettings"); Pump();
            Check(settings.WindowState == FormWindowState.Normal && speech.Text == "de" && !settings.IsDisposed,
                "Settings minimize/reopen/close remains usable, round " + (round + 1));
            settings.Close(); Pump();
        }
    }

    static Form PreparedReply(MainForm app)
    {
        // Build first so its normal FitToDisplay callback can be removed before
        // showing. Opening this prepared instance still uses the production path.
        Call(app, "BuildReplyPractice");
        Form reply = Field<Form>(app, "practiceWindow");
        Isolate(reply);
        Call(app, "OpenReplyPractice"); Pump();
        return reply;
    }

    static void ReplyFlows(MainForm app)
    {
        Form first = PreparedReply(app);
        TextBox draft = Field<TextBox>(app, "practiceDraft"); draft.Text = "Hello";
        first.WindowState = FormWindowState.Minimized; Pump();
        Call(app, "OpenReplyPractice"); Pump();
        Check(first.WindowState == FormWindowState.Normal && draft.Text == "Hello", "Reopening minimized reply practice restores its draft");
        first.Close(); Pump();
        Check(first.IsDisposed, "Reply practice closes and disposes its independent controls");
        Call(app, "RefreshPracticeControls");
        Form second = PreparedReply(app);
        Check(second.Visible && !second.IsDisposed && !Object.ReferenceEquals(first, second), "Reply practice rebuilds a fresh usable window after close");
        Check(Field<TextBox>(app, "practiceDraft").Text.Length == 0 && !Field<Button>(app, "practiceAction").Enabled,
            "Fresh disconnected reply practice has an empty draft and cannot submit");
        second.Close(); Pump();
        Call(app, "RefreshPracticeControls");
        Check(second.IsDisposed, "Repeated reply close leaves no disposed-control event failure");
    }

    static void CaptionFlows()
    {
        var state = new VrCaptionState();
        for (int round = 0; round < 3; round++)
        {
            using (var window = new VrCaptionWindow(state))
            {
                Isolate(window); window.Show(); Pump();
                window.RefreshCaptions();
                window.Size = new Size(710 + round * 20, 380); Pump();
                window.Close(); Pump();
                Check(window.IsDisposed, "Caption card close/recreate retires its timer and controls, round " + (round + 1));
            }
        }
    }

    static void PausedReadStatus(MainForm app)
    {
        Put(app, "sessionPaused", true);
        Put(app, "oneShotPending", true);
        string input = (string)typeof(MainForm).GetMethod("VrCaptureInput", Instance).Invoke(app, null);
        Check(app.SessionStatusText == "Reading screen" && input == "Reading selected screen area",
            "A manual screen read while paused reports the active read in both status and caption footer");
        Put(app, "oneShotPending", false);
        input = (string)typeof(MainForm).GetMethod("VrCaptureInput", Instance).Invoke(app, null);
        Check(app.SessionStatusText == "Paused" && input == "Translation paused" && app.SessionPaused,
            "Completing the manual read restores paused status without clearing saved pause intent");
        Put(app, "sessionPaused", false);
    }

    [STAThread] static int Main(string[] args)
    {
        try
        {
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += delegate(object sender, System.Threading.ThreadExceptionEventArgs e) { uiError = e.Exception; };
            Application.EnableVisualStyles();
            using (var app = new MainForm())
            {
                Isolate(app);
                Put(app, "screenArmed", false);
                Form settings = Field<Form>(app, "settingsForm"); Isolate(settings);
                app.Show(); Pump();
                SettingsFlows(app, settings);
                ReplyFlows(app);
                CaptionFlows();
                PausedReadStatus(app);
                foreach (string page in new[] { "settings", "audio", "history", "live", "history", "live" }) app.ShowSessionPage(page);
                Pump();
                Check(Field<object>(app, "worker") == null && !Field<bool>(app, "audioWanted") && !Field<bool>(app, "screenWanted"),
                    "Dialog and page exploration starts no worker or capture source");
                Call(app, "OpenSettings"); Pump();
                Form reply = PreparedReply(app);
                app.Close(); Pump();
                Check(app.IsDisposed && settings.IsDisposed && reply.IsDisposed, "Closing the app retires its owned Settings and reply windows");
            }
            Check(uiError == null, "All dialog lifecycle flows complete without an unhandled UI event");
            Console.WriteLine(passed + " UI flow checks passed; isolated windows only.");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
