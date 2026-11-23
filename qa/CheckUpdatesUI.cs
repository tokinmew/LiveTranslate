using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
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
    private static string Normalize(string value)
    {
        return (string)typeof(MainForm).GetMethod("NormalizedFeed", BindingFlags.Static | BindingFlags.NonPublic)
            .Invoke(null, new object[]{value});
    }
    private static bool Rejects(string value)
    {
        try { Normalize(value); }
        catch (TargetInvocationException e) { return e.InnerException is InvalidDataException; }
        return false;
    }
    private static void Click(Button button)
    {
        typeof(Button).GetMethod("OnClick",Instance).Invoke(button,new object[]{EventArgs.Empty});
    }
    private static void CheckSource(string preference, string local, string expected, string mode, string name)
    {
        object[] args = { preference, local, null };
        string source = (string)typeof(MainForm).GetMethod("ReadUpdateSource", BindingFlags.Static | BindingFlags.NonPublic)
            .Invoke(null, args);
        Check(source == expected && args[2].ToString() == mode, name);
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
                var start = new System.Diagnostics.ProcessStartInfo(fixture, "--fixture") { UseShellExecute = false, WorkingDirectory = root };
                using (var child = System.Diagnostics.Process.Start(start))
                {
                    child.WaitForExit();
                    if (child.ExitCode != 0) throw new Exception("Update source fixture failed.");
                }
            }
            finally { Directory.Delete(root, true); }
            return;
        }
        const string repo = "https://github.com/tokinmew/LiveTranslate";
        string basePath = AppDomain.CurrentDomain.BaseDirectory;
        string preference = Path.Combine(basePath, "data", "app-update-source.txt");
        string fixtureFeed = Path.Combine(basePath, "latest.json");
        CheckSource(preference, fixtureFeed, repo, "Automatic", "fresh install selects GitHub without a local feed");
        File.WriteAllText(fixtureFeed, "{}");
        CheckSource(preference, fixtureFeed, fixtureFeed, "ManagedLocal", "an existing bootstrap feed still works");
        using (var f = new MainForm())
        {
            TextBox source = Field<TextBox>(f,"updateSource");
            Click(Field<Button>(f,"githubUpdate"));
            Check(source.Text == repo && Field<object>(f,"releaseSourceMode").ToString() == "Custom","select project release source");
            CheckSource(preference, fixtureFeed, repo, "Custom", "explicit GitHub persists over an installed local feed");
            Check(Field<Label>(f,"updateSourceLabel").Text.Contains("stable"),"stable GitHub channel identified");
            Check(Field<Label>(f,"updateSourceHint").Text.Contains("gh auth login"),"private access guidance");
            Check(!Field<Button>(f,"installUpdate").Enabled,"switching source requires fresh update offer");
            source.Text = "https://github.com/example/Another-Release/";
            Check(Normalize(source.Text) == "https://github.com/example/Another-Release","custom repository with trailing slash");
            Check(Rejects(repo + "/releases/latest"),"repository subpath rejected");
            Check(Rejects("https://token@github.com/org/project"),"embedded credentials rejected");
            Check(Rejects(repo + "?token=example"),"query data rejected");
            Check(Rejects("http://github.com/org/project"),"remote cleartext rejected");
            Check(Normalize("https://updates.example/latest.json") == "https://updates.example/latest.json","existing HTTPS manifest preserved");
            Click(Field<Button>(f,"defaultUpdate"));
            string installed = Path.Combine(basePath, "updates", "feed", "latest.json");
            Check(source.Text == installed && Field<object>(f, "releaseSourceMode").ToString() == "Bundled", "select the installed signed release without browsing");
            File.Delete(fixtureFeed);
            CheckSource(preference, fixtureFeed, installed, "Bundled", "offline selection reopens against the installation folder");
            Click(Field<Button>(f, "automaticUpdate"));
            CheckSource(preference, fixtureFeed, repo, "Automatic", "automatic selection persists independently of explicit GitHub");
            Check(Field<Label>(f, "updateSourceLabel").Text == "Automatic updates", "automatic channel is visible");
            Check(Field<Label>(f, "updateSourceHint").Text.Contains("bundled"), "automatic fallback described");
            source.Clear();
            Check(Normalize(source.Text) == repo && Field<object>(f,"releaseSourceMode").ToString() == "Automatic","clearing input restores GitHub without starting a local server");
            Check(Field<System.Diagnostics.Process>(f,"worker")==null,"no real capture in hidden UI");
        }
        string custom = Path.Combine(basePath, "custom", "latest.json");
        File.WriteAllText(preference, custom);
        CheckSource(preference, fixtureFeed, custom, "Custom", "legacy custom manifest path preserved");
        File.WriteAllText(preference, "https://updates.example/latest.json");
        CheckSource(preference, fixtureFeed, "https://updates.example/latest.json", "Custom", "legacy custom HTTPS preserved");
        File.WriteAllText(preference, "invalid source");
        CheckSource(preference, fixtureFeed, repo, "Automatic", "damaged preference falls back to GitHub");
        CheckAutomaticDashboard(basePath, preference, repo);
        Console.WriteLine(count + " update UI checks passed.");
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

    private static void CheckAutomaticDashboard(string root, string preference, string repo)
    {
        string runtime = Directory.CreateDirectory(Path.Combine(root, "runtime")).FullName;
        string backend = Directory.CreateDirectory(Path.Combine(root, "backend")).FullName;
        File.Copy(Assembly.GetExecutingAssembly().Location, Path.Combine(runtime, "python.exe"));
        foreach (string helper in new[] { "installed_feed.py", "app_updates.py" })
            File.WriteAllText(Path.Combine(backend, helper), "");
        string oldSource = Path.Combine(root, "LiveTranslate-0.6.8-Local-Update-Feed", "latest.json");
        File.WriteAllText(preference, oldSource);
        var json = new JavaScriptSerializer();
        File.WriteAllText(Path.Combine(root, "installed_feed.py.fixture"),
            json.Serialize(new { ok = true, version = "0.6.8", migrate_source = oldSource }));
        File.WriteAllText(Path.Combine(root, "app_updates.py.fixture"),
            json.Serialize(new { ok=true, available=false, status="bundled", version="0.6.8", github_status="unpublished" }));
        string calls = Path.Combine(root, "calls.txt");
        using (var window = new MainForm())
        {
            var startup = typeof(MainForm).GetMethod("StartBundledFeed", Instance);
            Task first = (Task)startup.Invoke(window, null);
            Task second = (Task)startup.Invoke(window, null);
            Check(Object.ReferenceEquals(first, second), "startup uses a single initialization task");
            PumpUntil(() => first.IsCompleted);
            Check(File.ReadAllText(preference) == "automatic" && Field<TextBox>(window,"updateSource").Text == repo,
                "matching verified source migrates to automatic");
            Check(File.ReadAllLines(calls).Length == 1 && File.ReadAllLines(calls)[0].StartsWith("installed_feed.py "),
                "startup initializes locally without checking GitHub");
            Click(Field<Button>(window,"checkUpdates"));
            PumpUntil(() => Field<object>(window, "updateJob") == null);
            string state = Field<Label>(window, "updateState").Text;
            Check(state.Contains("bundled release 0.6.8") && state.Contains("no published stable release") &&
                !Field<Button>(window,"installUpdate").Enabled, "bundled result identifies local version and empty GitHub with no install offer");
            string[] used = File.ReadAllLines(calls);
            Check(used.Length == 2 && used[1].Contains("--automatic") && used[1].Contains(repo), "automatic check dispatches with official source");
            Click(Field<Button>(window,"githubUpdate"));
            File.WriteAllText(Path.Combine(root, "app_updates.py.fixture"),
                json.Serialize(new { ok=true, available=false, status="unpublished" }));
            Click(Field<Button>(window,"checkUpdates"));
            PumpUntil(() => Field<object>(window, "updateJob") == null);
            Check(!File.ReadAllLines(calls)[2].Contains("--automatic") && Field<Label>(window, "updateState").Text.Contains("No stable release"),
                "manual GitHub checks stay on GitHub");
            Click(Field<Button>(window, "defaultUpdate"));
            File.WriteAllText(Path.Combine(root, "app_updates.py.fixture"),
                json.Serialize(new { ok = true, available = false, version = "0.6.9" }));
            Click(Field<Button>(window, "checkUpdates"));
            PumpUntil(() => Field<object>(window, "updateJob") == null);
            string localCall = File.ReadAllLines(calls)[3];
            Check(localCall.Contains("--bundled") && !localCall.Contains("--serve-local") &&
                Field<Label>(window, "updateState").Text.Contains("Verified bundled release 0.6.9"),
                "bundled button checks the authenticated installed copy offline");
        }
        File.WriteAllText(preference, oldSource);
        using (var window = new MainForm())
        {
            Task pending = (Task)typeof(MainForm).GetMethod("StartBundledFeed", Instance).Invoke(window, null);
            Click(Field<Button>(window,"githubUpdate"));
            PumpUntil(() => pending.IsCompleted);
            Check(File.ReadAllText(preference) == repo && Field<object>(window,"releaseSourceMode").ToString() == "Custom",
                "an explicit source change wins over background migration");
        }
    }
}
