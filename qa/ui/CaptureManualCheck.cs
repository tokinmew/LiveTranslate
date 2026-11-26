using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using LiveTranslate;

// Only this program's authored source window is sampled. No user screen region,
// audio device, worker startup, network request or screenshot file is used.
internal static class CaptureManualCheck
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr handle, out RectangleNative rect);
    [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr handle, ref Point point);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll", EntryPoint="GetPropW", CharSet=CharSet.Unicode)] static extern IntPtr GetProp(IntPtr window, string name);
    [StructLayout(LayoutKind.Sequential)] struct RectangleNative { internal int Left, Top, Right, Bottom; }
    static void Put(MainForm app, string name, object value) { typeof(MainForm).GetField(name, Private).SetValue(app, value); }
    static T Get<T>(MainForm app, string name) { return (T)typeof(MainForm).GetField(name, Private).GetValue(app); }
    static void Check(bool value, string label) { if (!value) throw new Exception(label); Console.WriteLine("PASS " + label); }
    static void Isolate(MainForm app)
    {
        var events = (EventHandlerList)typeof(Component).GetProperty("Events", Private).GetValue(app, null);
        foreach (string name in new[] { "EVENT_LOAD", "EVENT_SHOWN" })
        {
            object key = typeof(Form).GetField(name, Static).GetValue(null);
            if (events[key] != null) events.RemoveHandler(key, events[key]);
        }
        Put(app, "screenArmed", false);
    }
    static string Quote(string value) { return "\"" + value.Replace("\"", "\\\"") + "\""; }
    [STAThread] static int Main(string[] args)
    {
        try { SetProcessDpiAwarenessContext(new IntPtr(-4)); } catch (EntryPointNotFoundException) { }
        Application.EnableVisualStyles();
        if (args.Length > 0 && args[0] == "--source")
        {
            using (var source = new Form { Text = "LiveTranslate authored Japanese capture QA", ClientSize = new Size(620, 180),
                ShowInTaskbar = false, StartPosition = FormStartPosition.Manual, Location = new Point(90, 100) })
            {
                source.Controls.Add(new Label { Dock = DockStyle.Fill, Text = "窓を開けてください。", Font = new Font("Yu Gothic", 30),
                    ForeColor = Color.White, BackColor = Color.FromArgb(20, 27, 37), TextAlign = ContentAlignment.MiddleCenter });
                source.Shown += delegate {
                    Console.WriteLine(source.Handle.ToInt64()); Console.Out.Flush();
                    new Thread(delegate() { Console.ReadLine(); if (!source.IsDisposed) source.BeginInvoke((MethodInvoker)delegate { source.Close(); }); }) { IsBackground = true }.Start();
                };
                Application.Run(source);
            }
            return 0;
        }
        Process target = null;
        try
        {
            string appRoot = args[0], repository = args[1];
            var sourceStart = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location, "--source") {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true,
                RedirectStandardOutput = true, RedirectStandardError = true };
            target = Process.Start(sourceStart);
            var sourceLine = target.StandardOutput.ReadLineAsync();
            if (!sourceLine.Wait(10000)) throw new Exception("Authored source window did not start.");
            IntPtr sourceHandle = new IntPtr(Int64.Parse(sourceLine.Result));
            RectangleNative client; Point origin = Point.Empty;
            if (!GetClientRect(sourceHandle, out client) || !ClientToScreen(sourceHandle, ref origin)) throw new Exception("Source bounds unavailable.");
            Rectangle capture = new Rectangle(origin.X, origin.Y, client.Right - client.Left, client.Bottom - client.Top);
            using (var app = new MainForm())
            {
                Isolate(app); app.ShowInTaskbar = false; app.StartPosition = FormStartPosition.Manual;
                app.Location = new Point(60, 60); app.Show(); app.Activate(); Application.DoEvents();
                Put(app, "selectedRegion", (Rectangle?)capture);
                IntPtr foreground = GetForegroundWindow();
                Check(app.Bounds.Contains(capture) && foreground == app.Handle, "Dashboard visibly covers the complete authored Japanese source");
                string arguments = "-I -B -X utf8 " + Quote(Path.Combine(repository, "qa/ui/capture_manual_probe.py")) +
                    " " + Quote(repository) + " " + Quote(appRoot) + " " + app.Handle.ToInt64() + " " + capture.X + " " + capture.Y + " " + capture.Width + " " + capture.Height;
                using (var probe = new Process())
                {
                    probe.StartInfo = new ProcessStartInfo(Path.Combine(appRoot, "runtime/python.exe"), arguments) {
                        UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                        WorkingDirectory = appRoot };
                    probe.Start(); Put(app, "worker", probe);
                    var output = probe.StandardOutput.ReadToEndAsync(); var error = probe.StandardError.ReadToEndAsync();
                    DateTime deadline = DateTime.UtcNow.AddSeconds(30);
                    while (!probe.HasExited && DateTime.UtcNow < deadline) { Application.DoEvents(); Thread.Sleep(10); }
                    if (!probe.HasExited) { probe.Kill(); throw new Exception("Manual capture probe timed out."); }
                    Console.Write(output.GetAwaiter().GetResult()); Console.Error.Write(error.GetAwaiter().GetResult());
                    Put(app, "worker", null);
                    Check(probe.ExitCode == 0, "Real desktop capture clears only app-owned obstruction and recognizes the underlying Japanese sentence");
                }
                DateTime restoredBy = DateTime.UtcNow.AddSeconds(4);
                while (Get<int>(app, "sampleToken") != 0 && DateTime.UtcNow < restoredBy) { Application.DoEvents(); Thread.Sleep(10); }
                Check(app.Visible && app.Opacity == 1 && app.Location == new Point(60, 60), "Manual capture restores opacity and leaves visibility and placement unchanged");
                Check(GetForegroundWindow() == foreground, "Manual sampling preserves keyboard foreground focus");
                Check(GetProp(app.Handle, "LiveTranslate.ManualSampleHidden.v1") == IntPtr.Zero && Get<int>(app, "sampleToken") == 0,
                    "No manual-hide marker or lease survives successful or failing capture");
            }
            Console.WriteLine("Manual desktop capture/native OCR check passed; authored application windows only.");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally
        {
            if (target != null)
            {
                try { if (!target.HasExited) { target.StandardInput.WriteLine(); if (!target.WaitForExit(5000)) target.Kill(); } }
                catch (InvalidOperationException) { }
                target.Dispose();
            }
        }
    }
}
