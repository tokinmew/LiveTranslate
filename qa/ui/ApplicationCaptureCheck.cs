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
                { "image", Convert.ToBase64String(stream.ToArray()) }, { "width", 120 }, { "height", 60 }, { "source", "application" } };
        }
    }
    static void Pending(MainForm app, int id)
    { Field<Dictionary<int, PendingRequest>>(app, "pending")[id] = new PendingRequest("preview_screen", "", ""); Put(app, "capturePreviewRequest", id); }

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
            }
            Console.WriteLine(passed + " application capture UI checks passed.");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
