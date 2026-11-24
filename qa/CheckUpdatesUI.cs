using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using LiveTranslate;

internal static class CheckUpdatesUI
{
    private const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    private static int count;
    private static void Check(bool passed, string name)
    {
        if (!passed) throw new Exception(name);
        Console.WriteLine("PASS " + name);
        count++;
    }
    private static T Field<T>(MainForm form, string name)
    {
        return (T)typeof(MainForm).GetField(name, Instance).GetValue(form);
    }
    private static void Click(Button button)
    {
        typeof(Button).GetMethod("OnClick",Instance).Invoke(button,new object[]{EventArgs.Empty});
    }
    private static IEnumerable<Control> Children(Control parent)
    {
        foreach (Control child in parent.Controls)
        {
            yield return child;
            foreach (Control nested in Children(child)) yield return nested;
        }
    }
    private static void PumpUntil(Func<bool> done)
    {
        var deadline = Stopwatch.StartNew();
        while (!done() && deadline.Elapsed < TimeSpan.FromSeconds(10))
        {
            Application.DoEvents();
            Thread.Sleep(5);
        }
        if (!done()) throw new Exception("Timed out waiting for the synthetic update helper.");
    }
    [STAThread]
    private static void Main(string[] args)
    {
        if (args.Length != 0 && args[0] == "-I")
        {
            string helper = Path.GetFileName(args[5]);
            File.AppendAllText("calls.txt", helper + " " + String.Join(" ", args, 6, args.Length - 6) + Environment.NewLine);
            Console.WriteLine(File.ReadAllText(helper + ".fixture"));
            return;
        }
        if (args.Length == 0)
        {
            string root = Path.Combine(Path.GetTempPath(), "LiveTranslate-update-ui-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                string fixture = Path.Combine(root, "CheckUpdatesUI.exe");
                File.Copy(Assembly.GetExecutingAssembly().Location, fixture);
                var start = new ProcessStartInfo(fixture, "--fixture") { UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true, WorkingDirectory = root };
                using (var child = Process.Start(start))
                {
                    var stdout = child.StandardOutput.ReadToEndAsync();
                    var stderr = child.StandardError.ReadToEndAsync();
                    child.WaitForExit();
                    Console.Write(stdout.GetAwaiter().GetResult());
                    Console.Error.Write(stderr.GetAwaiter().GetResult());
                    if (child.ExitCode != 0) throw new Exception("GitHub update UI fixture failed.");
                }
            }
            finally { Directory.Delete(root, true); }
            return;
        }
        string basePath = AppDomain.CurrentDomain.BaseDirectory;
        string preference = Path.Combine(basePath, "data", "app-update-source.txt");
        Directory.CreateDirectory(Path.GetDirectoryName(preference));
        File.WriteAllText(preference, Path.Combine(basePath, "LiveTranslate-0.6.8-Local-Update-Feed", "latest.json"));
        Directory.CreateDirectory(Path.Combine(basePath, "updates", "feed"));
        File.WriteAllText(Path.Combine(basePath, "updates", "feed", "latest.json"), "{\"version\":\"99.0.0\"}");
        string runtime = Directory.CreateDirectory(Path.Combine(basePath, "runtime")).FullName;
        string backend = Directory.CreateDirectory(Path.Combine(basePath, "backend")).FullName;
        File.Copy(Assembly.GetExecutingAssembly().Location, Path.Combine(runtime, "python.exe"));
        File.WriteAllText(Path.Combine(backend, "app_updates.py"), "");
        var json = new JavaScriptSerializer();
        Version assemblyVersion = typeof(MainForm).Assembly.GetName().Version;
        string installed = assemblyVersion.ToString(3);
        string nextPatch = new Version(assemblyVersion.Major, assemblyVersion.Minor, assemblyVersion.Build + 1).ToString(3);
        string response = Path.Combine(basePath, "app_updates.py.fixture");
        string calls = Path.Combine(basePath, "calls.txt");
        using (var window = new MainForm())
        {
            var tabs = Field<TabControl>(window, "settingsTabs");
            TabPage updates = null;
            foreach (TabPage page in tabs.TabPages) if (page.Text == "Updates") updates = page;
            Check(updates != null, "updates tab remains available");
            bool editableSource = false, alternateSource = false, officialAddress = false;
            foreach (Control control in Children(updates))
            {
                editableSource |= control is TextBox;
                alternateSource |= control is Button && (control.Text.Contains("manifest") || control.Text.Contains("Bundled") || control.Text.Contains("Automatic") || control.Text.Contains("local"));
                officialAddress |= control.Text == "https://github.com/tokinmew/LiveTranslate";
            }
            Check(!editableSource && !alternateSource && officialAddress, "only the official GitHub source is presented");
            Check(!Field<Label>(window, "updateSourceHint").Text.Contains("gh auth"), "public update check needs no CLI sign-in");
            Check(!File.Exists(calls), "startup neither reads a local feed nor checks the network");
            Check(!Field<Button>(window,"installUpdate").Enabled, "installation waits for a verified GitHub offer");
            Check(Field<Process>(window,"worker") == null, "hidden UI tests do not start capture");

            File.WriteAllText(response, json.Serialize(new { ok=true, available=true, version=nextPatch, sha256=new string('a',64), size=1024 }));
            Click(Field<Button>(window,"checkUpdates"));
            PumpUntil(() => Field<object>(window,"updateJob") == null);
            Check(Field<Label>(window,"updateState").Text.Contains("GitHub release v" + nextPatch) && Field<Button>(window,"installUpdate").Enabled,
                "a newer GitHub version enables download and restart");
            string[] used = File.ReadAllLines(calls);
            Check(used.Length == 1 && used[0] == "app_updates.py check --installed " + installed, "legacy local preference cannot change the GitHub-only helper command");

            File.WriteAllText(response, json.Serialize(new { ok=false, error="The release changed after checking. Check again before installing." }));
            Click(Field<Button>(window,"installUpdate"));
            PumpUntil(() => Field<object>(window,"updateJob") == null);
            string prepare = "app_updates.py prepare --installed " + installed + " --version " + nextPatch + " --sha256 " + new string('a',64);
            Check(File.ReadAllLines(calls)[1] == prepare && !Field<Button>(window,"installUpdate").Enabled,
                "download preparation binds the selected GitHub version and digest and requires recheck after a changed release");
            File.WriteAllText(response, json.Serialize(new { ok=true, available=true, version=nextPatch, sha256=new string('a',64), size=1024 }));
            Click(Field<Button>(window,"checkUpdates"));
            PumpUntil(() => Field<object>(window,"updateJob") == null);

            File.WriteAllText(response, json.Serialize(new { ok=false, error="GitHub could not be reached. Check your connection and retry." }));
            Click(Field<Button>(window,"checkUpdates"));
            PumpUntil(() => Field<object>(window,"updateJob") == null);
            string status = Field<Label>(window,"updateState").Text;
            Check(status.Contains("GitHub could not be reached") && !status.Contains("up to date") && !Field<Button>(window,"installUpdate").Enabled,
                "connection failure is explicit and clears a stale release offer");

            File.WriteAllText(response, json.Serialize(new { ok=true, available=false, status="unpublished" }));
            Click(Field<Button>(window,"checkUpdates"));
            PumpUntil(() => Field<object>(window,"updateJob") == null);
            Check(Field<Label>(window,"updateState").Text.Contains("No stable release") && !Field<Button>(window,"installUpdate").Enabled,
                "an unpublished channel is not reported as up to date");

            File.WriteAllText(response, json.Serialize(new { ok=true, available=false, status="bundled", version="0.6.8", github_status="unavailable" }));
            Click(Field<Button>(window,"checkUpdates"));
            PumpUntil(() => Field<object>(window,"updateJob") == null);
            Check(Field<Label>(window,"updateState").Text.Contains("could not finish") && !Field<Button>(window,"installUpdate").Enabled,
                "a legacy bundled fallback result cannot masquerade as the latest GitHub release");

            File.WriteAllText(response, json.Serialize(new { ok=true, available=false }));
            Click(Field<Button>(window,"checkUpdates"));
            PumpUntil(() => Field<object>(window,"updateJob") == null);
            Check(!Field<Label>(window,"updateState").Text.Contains("up to date"), "an incomplete response cannot report the app current");

            File.WriteAllText(response, json.Serialize(new { ok=true, available=true, version=nextPatch, sha256=new string('z',64), size=1024 }));
            Click(Field<Button>(window,"checkUpdates"));
            PumpUntil(() => Field<object>(window,"updateJob") == null);
            Check(!Field<Button>(window,"installUpdate").Enabled, "a malformed digest cannot enable installation");

            File.WriteAllText(response, json.Serialize(new { ok=true, available=false, version=installed }));
            Click(Field<Button>(window,"checkUpdates"));
            PumpUntil(() => Field<object>(window,"updateJob") == null);
            Check(Field<Label>(window,"updateState").Text.Contains("up to date with GitHub"), "a successful current GitHub response is identified");
            bool fixedChannel = true;
            foreach (string call in File.ReadAllLines(calls)) fixedChannel &= call == "app_updates.py check --installed " + installed || call == prepare;
            Check(fixedChannel, "all checks use the same official channel");
            Check(File.ReadAllText(preference).Contains("0.6.8-Local-Update-Feed"), "ignoring legacy source preferences preserves user files");
        }
        Console.WriteLine(count + " GitHub-only update UI checks passed.");
    }
}
