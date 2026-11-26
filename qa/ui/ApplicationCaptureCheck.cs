using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using LiveTranslate;

// App-owned synthetic windows only. No real screen capture, worker or user files.
internal static class ApplicationCaptureCheck
{
    [DllImport("user32.dll", EntryPoint = "GetPropW", CharSet = CharSet.Unicode)] static extern IntPtr GetMarker(IntPtr handle, string name);
    [DllImport("user32.dll")] static extern bool GetWindowDisplayAffinity(IntPtr handle, out uint affinity);
    const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;
    static int passed;
    static T Field<T>(MainForm app, string name) { return (T)typeof(MainForm).GetField(name, Instance).GetValue(app); }
    static void Put(MainForm app, string name, object value) { typeof(MainForm).GetField(name, Instance).SetValue(app, value); }
    static object Call(MainForm app, string name, params object[] args) { return typeof(MainForm).GetMethod(name, Instance).Invoke(app, args); }
    static void Check(bool value, string label) { if (!value) throw new Exception(label); passed++; Console.WriteLine("PASS " + label); }
    static void Isolate(Form form)
    {
        var events = (EventHandlerList)typeof(Component).GetProperty("Events", Instance).GetValue(form, null);
        foreach (string name in new[] { "EVENT_LOAD", "EVENT_SHOWN" })
        {
            object key = typeof(Form).GetField(name, Static).GetValue(null);
            if (events[key] != null) events.RemoveHandler(key, events[key]);
        }
        form.ShowInTaskbar = false; form.StartPosition = FormStartPosition.Manual;
        form.Location = new Point(SystemInformation.VirtualScreen.Right + 200, 40);
    }
    static Dictionary<string, object> Frame(int id)
    {
        using (Bitmap image = new Bitmap(120, 60))
        using (Graphics draw = Graphics.FromImage(image))
        using (MemoryStream stream = new MemoryStream())
        {
            draw.Clear(Color.Teal); image.Save(stream, ImageFormat.Jpeg);
            return new Dictionary<string, object> { { "type", "screen_preview" }, { "id", id },
                { "image", Convert.ToBase64String(stream.ToArray()) }, { "width", 120 }, { "height", 60 }, { "source", "application" },
                { "diagnostics", new Dictionary<string, object> { { "raw_ocr", "Home / unverified" }, { "accepted_ocr", "" }, { "masked_percent", 0 } } } };
        }
    }
    static void Pending(MainForm app, int id)
    { Field<Dictionary<int, PendingRequest>>(app, "pending")[id] = new PendingRequest("preview_screen", "", ""); Put(app, "capturePreviewRequest", id); }

    static void SeedAudioDiagnostic(MainForm app)
    {
        Put(app, "audioWanted", true); Put(app, "audioSession", "retired-audio");
        Call(app, "HandleAudioDiagnostic", new Dictionary<string, object> { { "session_id", "retired-audio" },
            { "stage", "signal" }, { "source", "pc" }, { "endpoint", 1 }, { "level", 80 }, { "message", "Old signal" } });
        Call(app, "HandleAudioDiagnostic", new Dictionary<string, object> { { "session_id", "retired-audio" },
            { "stage", "recognition" }, { "language", "ja" }, { "recognized", "古い音声" }, { "message", "Old recognition" } });
    }

    static void ReconnectedPreviewQueues(MainForm app, string cause)
    {
        // Send uses a live process identity only to check HasExited. The wire
        // goes to an in-memory stream; no worker is started and no capture runs.
        using (Process identity = Process.GetCurrentProcess())
        using (var wire = new MemoryStream())
        using (var writer = new StreamWriter(wire))
        {
            writer.AutoFlush = true;
            Put(app, "worker", identity); Put(app, "inputWriter", writer); Put(app, "connected", true);
            try
            {
                int previous = Field<int>(app, "requestId");
                Call(app, "RequestCapturePreview");
                int queued = Field<int>(app, "capturePreviewRequest");
                Check(queued > previous && Field<Dictionary<int, PendingRequest>>(app, "pending").ContainsKey(queued) &&
                    System.Text.Encoding.UTF8.GetString(wire.ToArray()).Contains("preview_screen"),
                    "A reconnected engine can queue a fresh preview after " + cause);
                Call(app, "HandleMessage", Frame(queued));
                Form preview = Field<Form>(app, "capturePreview");
                preview.Hide();
                Check(preview != null && !preview.IsDisposed && Field<int>(app, "capturePreviewRequest") == 0,
                    "The fresh preview response opens after " + cause);
            }
            finally
            {
                // Retire the identity before normal CloseWorker can ever run;
                // it must never wait on or terminate this fixture process.
                Put(app, "worker", null); Put(app, "inputWriter", null); Put(app, "connected", false);
                Call(app, "InvalidateCapturePreview");
            }
        }
    }

    [STAThread] static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        try
        {
            using (MainForm app = new MainForm())
            using (Form source = new Form { ClientSize = new Size(620, 240), StartPosition = FormStartPosition.Manual,
                                            Location = new Point(SystemInformation.VirtualScreen.Right + 500, 20) })
            {
                Isolate(app); Put(app, "screenArmed", false);
                IntPtr owner = app.Handle, native = source.Handle;
                ApplicationCaptureTarget a = new ApplicationCaptureTarget(native, (uint)Process.GetCurrentProcess().Id, "Synthetic source A");
                ApplicationCaptureTarget b = new ApplicationCaptureTarget(native, (uint)Process.GetCurrentProcess().Id, "Synthetic source B");
                Call(app, "SelectApplication", a);
                Check(Field<ApplicationCaptureTarget>(app, "captureApplication") == a && !Field<Rectangle?>(app, "selectedRegion").HasValue &&
                      Field<string>(app, "targetDisplay") == null, "Application selection clears conflicting screen targets");
                Rectangle bounds = (Rectangle)Call(app, "CaptureBounds");
                Check(bounds.Size == new Size(620, 240), "Application client dimensions stay independent of the dashboard size");
                var parameters = (Dictionary<string, object>)Call(app, "ScreenArguments", "fixture-session");
                var region = (Dictionary<string, object>)parameters["region"];
                Check(region.Count == 2 && (long)region["window"] == native.ToInt64() && (long)region["process"] == Process.GetCurrentProcess().Id,
                      "Window capture sends only the chosen handle and its matching process identity");
                Check(ApplicationCapture.Bounds(new ApplicationCaptureTarget(native, (uint)Process.GetCurrentProcess().Id + 1, "wrong")).IsEmpty,
                      "A reused window handle cannot silently capture another process");
                Pending(app, 101);
                Call(app, "SelectApplication", b);
                Call(app, "HandleMessage", Frame(101));
                Check(Field<Form>(app, "capturePreview") == null && Field<int>(app, "capturePreviewRequest") == 0,
                      "A late source A preview is ignored after selecting source B");
                Pending(app, 102);
                Call(app, "HandleMessage", Frame(102));
                Form preview = Field<Form>(app, "capturePreview");
                preview.Hide();
                Check(preview != null && !preview.IsDisposed && Field<int>(app, "capturePreviewRequest") == 0,
                      "A fresh source B response opens a bounded preview and clears its pending request");
                Check(GetMarker(preview.Handle, "LiveTranslate.CapturePreview") != IntPtr.Zero,
                      "A newly opened preview is marked for exclusion from an already-running desktop watcher");
                uint affinity;
                Check(GetWindowDisplayAffinity(preview.Handle, out affinity) && affinity == 0,
                      "Capture preview remains available to user screenshots and support tools");
                TextBox diagnostic = (TextBox)preview.Controls.Find("CaptureRecognitionDetails", true)[0];
                Check(diagnostic.ReadOnly && diagnostic.Text.Contains("Home / unverified") && diagnostic.Text.Contains("diagnostic only") &&
                      Field<RichTextBox>(app, "output").TextLength == 0,
                      "Unverified diagnostic OCR is selectable but never becomes a translated caption");
                Call(app, "SelectDisplay", (object)null);
                Check(preview.IsDisposed && Field<Form>(app, "capturePreview") == null && Field<ApplicationCaptureTarget>(app, "captureApplication") == null,
                      "Changing back to a display closes the stale application preview");
                Pending(app, 103);
                Call(app, "SelectDisplay", (object)null);
                Call(app, "HandleMessage", new Dictionary<string, object> { { "type", "error" }, { "id", 103 }, { "message", "Old source unavailable" } });
                Check(Field<Form>(app, "capturePreview") == null, "A stale preview failure cannot reopen or replace the new capture source");
                Put(app, "connected", true); Put(app, "capturePreviewRequest", 104);
                int sent = Field<int>(app, "requestId");
                Call(app, "RequestCapturePreview");
                Check(Field<int>(app, "capturePreviewRequest") == 104 && Field<int>(app, "requestId") == sent,
                      "Repeated preview clicks do not queue duplicate captures");
                Put(app, "connected", false); Call(app, "InvalidateCapturePreview");
                int historyBefore = Field<RichTextBox>(app, "output").TextLength;
                string covered = "The selected area is covered by a LiveTranslate window.";
                for (int attempt = 0; attempt < 2; attempt++)
                {
                    Put(app, "screenWanted", true); Put(app, "screenSession", "covered-" + attempt);
                    Call(app, "HandleMessage", new Dictionary<string, object> { { "type", "capture_state" }, { "channel", "screen" },
                        { "session_id", "covered-" + attempt }, { "state", "error" }, { "retryable", true }, { "message", covered } });
                }
                string afterRetry = Field<RichTextBox>(app, "output").Text;
                Check(afterRetry.IndexOf(covered, StringComparison.Ordinal) == afterRetry.LastIndexOf(covered, StringComparison.Ordinal) &&
                      afterRetry.Length > historyBefore && Field<Label>(app, "status").Text == covered,
                      "Unchanged automatic retry errors keep status visible without spamming the transcript");
                Put(app, "screenWanted", true); Put(app, "screenSession", "sample-clears-error");
                Call(app, "HandleMessage", new Dictionary<string, object> { { "type", "capture_state" }, { "channel", "screen" },
                    { "session_id", "sample-clears-error" }, { "state", "active" }, { "sampled", true }, { "message", "Scanning." } });
                Call(app, "HandleMessage", new Dictionary<string, object> { { "type", "capture_state" }, { "channel", "screen" },
                    { "session_id", "sample-clears-error" }, { "state", "error" }, { "retryable", true }, { "message", covered } });
                string afterRecovery = Field<RichTextBox>(app, "output").Text;
                Check(afterRecovery.LastIndexOf(covered, StringComparison.Ordinal) > afterRetry.LastIndexOf(covered, StringComparison.Ordinal),
                      "An actual successful sample resets the error episode for a later genuine failure");

                Pending(app, 105); SeedAudioDiagnostic(app);
                Process exited = new Process();
                Put(app, "worker", exited);
                Call(app, "HandleWorkerExit", exited);
                Check(Field<int>(app, "capturePreviewRequest") == 0 && !Field<bool>(app, "connected") &&
                    Field<AudioSignalMeter>(app, "audioSignalMeter").Level == 0 && Field<TextBox>(app, "audioRecognizedText").TextLength == 0,
                    "Unexpected worker exit retires the pending preview and old audio diagnostics");
                Call(app, "HandleMessage", Frame(105));
                Check(Field<Form>(app, "capturePreview") == null, "A retired worker's late preview cannot reopen a diagnostic window");
                ReconnectedPreviewQueues(app, "worker exit");

                Pending(app, 106); SeedAudioDiagnostic(app);
                Call(app, "CloseWorker");
                Check(Field<int>(app, "capturePreviewRequest") == 0 && Field<Form>(app, "capturePreview") == null &&
                    Field<AudioSignalMeter>(app, "audioSignalMeter").Level == 0 && Field<TextBox>(app, "audioRecognizedText").TextLength == 0,
                    "Intentional worker shutdown clears preview and measured/recognised audio state");
                ReconnectedPreviewQueues(app, "intentional shutdown");
            }
            Console.WriteLine(passed + " application capture UI checks passed.");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
