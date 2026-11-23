using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed partial class MainForm
    {
        private TextBox updateSource;
        private Label updateState, updateSourceLabel, updateSourceHint;
        private enum ReleaseSourceMode { Automatic, Custom, ManagedLocal }
        private ReleaseSourceMode releaseSourceMode;
        private bool preparingUpdate, waitingForInstaller;
        private Button checkUpdates, installUpdate, cancelUpdate, browseUpdate, defaultUpdate, githubUpdate, automaticUpdate;
        private Task bundledFeedStartup;
        private int sourceEditNumber;
        private ProgressBar updateActivity;
        private CancellationTokenSource updateJob;
        private string offeredVersion, offeredDigest;
        private bool restartCommitted;
        private const string ProjectRepository = "https://github.com/tokinmew/LiveTranslate";
        private const string ManagedLocalPreference = "managed-local";
        private const string AutomaticPreference = "automatic";
        private static readonly Regex GithubRepository = new Regex(
            @"\Ahttps://github\.com/[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?/(?<repo>[a-z0-9._-]{1,100})/?\z",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        private static bool IsGithubRepository(string value)
        {
            Match match = GithubRepository.Match(value);
            return match.Success && match.Groups["repo"].Value != "." && match.Groups["repo"].Value != "..";
        }

        private static string UpdateRoot { get { return AppDomain.CurrentDomain.BaseDirectory; } }
        private static string FeedPreference { get { return Path.Combine(UpdateRoot, "data", "app-update-source.txt"); } }

        private static string LocalFeed()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "LiveTranslate", "Releases", "latest.json");
        }

        private static string CurrentUpdateVersion()
        {
            Version v = typeof(MainForm).Assembly.GetName().Version;
            return v.Revision > 0 ? v.ToString(4) : v.ToString(3);
        }

        private static string NormalizedFeed(string input)
        {
            string value = input.Trim();
            if (value.Length == 0) return ProjectRepository;
            if (value.Length > 2048) throw new InvalidDataException("The update source is too long.");
            foreach (char c in value)
                if (Char.IsControl(c) || c == '"') throw new InvalidDataException("Invalid characters in the update source.");
            bool localHttp = value.StartsWith("http://", StringComparison.OrdinalIgnoreCase);
            if (localHttp || value.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            {
                Uri uri;
                if (value.IndexOf('\\') >= 0 || !Uri.TryCreate(value, UriKind.Absolute, out uri) ||
                    uri.Host.Length == 0 || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0)
                    throw new InvalidDataException("Enter a repository or manifest URL without credentials, a query or a fragment.");
                if (uri.Host.Equals("github.com", StringComparison.OrdinalIgnoreCase) && !uri.AbsolutePath.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                {
                    if (!IsGithubRepository(value))
                        throw new InvalidDataException("Use the GitHub repository address, such as https://github.com/OWNER/REPO.");
                    return value.TrimEnd('/');
                }
                if (localHttp)
                {
                    string authority = value.Substring("http://".Length).Split('/')[0];
                    string withPort = "127.0.0.1:" + uri.Port.ToString(CultureInfo.InvariantCulture);
                    if (uri.Host != "127.0.0.1" || uri.Port < 1 || !(authority == "127.0.0.1" || authority == withPort))
                        throw new InvalidDataException("Use HTTPS for a remote server, or 127.0.0.1 for a local HTTP server.");
                }
                return uri.AbsoluteUri;
            }
            if (value.StartsWith(@"\\?\") || value.StartsWith(@"\\.\"))
                throw new InvalidDataException("Choose a regular update manifest file.");
            if (!(value.StartsWith(@"\\") || (value.Length >= 3 && Char.IsLetter(value[0]) && value[1] == ':' &&
                  (value[2] == '\\' || value[2] == '/'))))
                throw new InvalidDataException("Choose an absolute manifest path or an HTTPS URL.");
            return Path.GetFullPath(value);
        }

        private static string ReadUpdateSource(string preference, string localFeed, out ReleaseSourceMode mode)
        {
            mode = ReleaseSourceMode.Automatic;
            try
            {
                if (File.Exists(preference) && new FileInfo(preference).Length <= 8192)
                {
                    string saved = File.ReadAllText(preference).Trim();
                    if (saved == AutomaticPreference || saved.Length == 0) return ProjectRepository;
                    if (saved == ManagedLocalPreference)
                    {
                        mode = ReleaseSourceMode.ManagedLocal;
                        return localFeed;
                    }
                    string custom = NormalizedFeed(saved);
                    mode = ReleaseSourceMode.Custom;
                    return custom;
                }
                // Early updater kits explicitly installed a per-user feed without a preference.
                if (!File.Exists(preference) && File.Exists(localFeed))
                {
                    mode = ReleaseSourceMode.ManagedLocal;
                    return localFeed;
                }
            }
            catch (Exception) { } // A corrupt preference cannot prevent dashboard startup.
            return ProjectRepository;
        }

        private static void SaveUpdateSource(string pref, string source, ReleaseSourceMode mode)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(pref));
            string temp = pref + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                string saved = mode == ReleaseSourceMode.ManagedLocal ? ManagedLocalPreference :
                    mode == ReleaseSourceMode.Automatic ? AutomaticPreference : source;
                File.WriteAllText(temp, saved, new UTF8Encoding(false));
                if (File.Exists(pref)) File.Replace(temp, pref, null);
                else File.Move(temp, pref);
            }
            finally { if (File.Exists(temp)) File.Delete(temp); }
        }

        private static string LastUpdateResult()
        {
            string result = Path.Combine(UpdateRoot, ".livetranslate-update", "last-result.txt");
            try
            {
                var file = new FileInfo(result);
                if (file.Exists && file.Length <= 4096)
                {
                    string line = File.ReadAllText(result).Trim();
                    if (line.Length != 0) return line.Length > 480 ? line.Substring(0, 480) : line;
                }
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            return "Check for a new version. Your models and settings stay installed.";
        }

        private void BuildUpdatesTab()
        {
            var page = SettingsPage("Updates");
            var layout = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
                ColumnCount = 1, Margin = Padding.Empty, BackColor = SystemColors.Window, ForeColor = paperInk };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            updateSourceLabel = new Label { AutoSize = true, Font = new Font(Font, FontStyle.Bold), Margin = new Padding(0, 0, 0, 6) };
            layout.Controls.Add(updateSourceLabel, 0, 0);
            updateSource = new TextBox { Dock = DockStyle.Top, BackColor = field, ForeColor = ink, Text = ReadUpdateSource(FeedPreference, LocalFeed(), out releaseSourceMode),
                AccessibleName = "GitHub repository, server URL or manifest file", Margin = new Padding(0, 0, 0, 6) };
            layout.Controls.Add(updateSource, 0, 1);
            var sources = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, Margin = new Padding(0) };
            automaticUpdate = UpdateButton("Automatic updates");
            automaticUpdate.Click += delegate { SetReleaseSource(ProjectRepository, ReleaseSourceMode.Automatic); };
            githubUpdate = UpdateButton("GitHub Releases");
            githubUpdate.Click += delegate { SetReleaseSource(ProjectRepository, ReleaseSourceMode.Custom); };
            browseUpdate = UpdateButton("Choose manifest");
            browseUpdate.Click += delegate
            {
                using (var d = new OpenFileDialog { Filter = "Update manifests (*.json)|*.json", CheckFileExists = true })
                    if (d.ShowDialog(settingsForm) == DialogResult.OK) SetReleaseSource(d.FileName, ReleaseSourceMode.Custom);
            };
            defaultUpdate = UpdateButton("Use local default");
            defaultUpdate.Click += delegate { SetReleaseSource(LocalFeed(), ReleaseSourceMode.ManagedLocal); };
            sources.Controls.Add(automaticUpdate);
            sources.Controls.Add(githubUpdate);
            sources.Controls.Add(browseUpdate);
            sources.Controls.Add(defaultUpdate);
            layout.Controls.Add(sources, 0, 2);
            updateSourceHint = new Label { AutoSize = true, MaximumSize = new Size(525, 0),
                ForeColor = ink, Margin = new Padding(0, 6, 0, 0) };
            layout.Controls.Add(updateSourceHint, 0, 3);
            updateState = new Label { Text = LastUpdateResult(),
                AutoSize = true, MaximumSize = new Size(540, 0), ForeColor = ink, Margin = new Padding(0, 16, 0, 6) };
            updateState.AccessibleRole = AccessibleRole.StatusBar;
            layout.Controls.Add(updateState, 0, 4);
            layout.SizeChanged += delegate
            {
                int width = Math.Max(1, layout.ClientSize.Width - 4);
                updateSourceHint.MaximumSize = updateState.MaximumSize = new Size(width, 0);
            };
            updateActivity = new ProgressBar { Dock = DockStyle.Top, Height = 6, MarqueeAnimationSpeed = 0,
                Style = ProgressBarStyle.Blocks, Margin = new Padding(0, 2, 0, 8) };
            layout.Controls.Add(updateActivity, 0, 5);
            var actions = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, Margin = new Padding(0) };
            checkUpdates = UpdateButton("Check for updates");
            checkUpdates.BackColor = accent;
            installUpdate = UpdateButton("Download and restart");
            cancelUpdate = UpdateButton("Cancel");
            checkUpdates.Click += delegate { RunUpdateAction(false); };
            installUpdate.Click += delegate { RunUpdateAction(true); };
            cancelUpdate.Click += delegate { if (updateJob != null && !preparingUpdate && !restartCommitted) updateJob.Cancel(); };
            actions.Controls.Add(checkUpdates);
            actions.Controls.Add(installUpdate);
            actions.Controls.Add(cancelUpdate);
            var history = UpdateButton("Changelog");
            history.Name = "Changelog";
            history.AccessibleName = "View changelog";
            history.Click += delegate {
                using (var window = new ReleaseHistoryWindow(Font)) window.ShowDialog(settingsForm);
            };
            actions.Controls.Add(history);
            layout.Controls.Add(actions, 0, 6);
            updateSource.TextChanged += delegate
            {
                sourceEditNumber++;
                releaseSourceMode = String.IsNullOrWhiteSpace(updateSource.Text) ? ReleaseSourceMode.Automatic : ReleaseSourceMode.Custom;
                ClearReleaseOffer();
            };
            AddSettingsBody(page, "App updates", "Installed version " + CurrentUpdateVersion() + ". Choose a release source and check for a new version.", layout, 0);
            settingsTabs.TabPages.Add(page);
            Shown += delegate { StartBundledFeed(); };
            FormClosed += delegate { if (updateJob != null && !preparingUpdate && !restartCommitted && !waitingForInstaller) updateJob.Cancel(); };
            RefreshUpdateActions();
        }

        private void SetReleaseSource(string value, ReleaseSourceMode mode)
        {
            updateSource.Text = value;
            sourceEditNumber++;
            releaseSourceMode = mode;
            ClearReleaseOffer();
            try { SaveUpdateSource(FeedPreference, value, mode); }
            catch (Exception) { updateState.Text += " The source could not be saved for next time."; }
        }

        private void ClearReleaseOffer()
        {
            offeredVersion = offeredDigest = null;
            updateState.Text = "Check this source for an update.";
            RefreshUpdateActions();
        }

        private Button UpdateButton(string caption)
        {
            var button = new ModernButton { Text = caption, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
                Padding = new Padding(8, 4, 8, 4), Margin = new Padding(0, 2, 8, 2),
                FlatStyle = FlatStyle.Flat, BackColor = field, ForeColor = ink, UseVisualStyleBackColor = false };
            button.FlatAppearance.BorderColor = border;
            return button;
        }

        private void RefreshUpdateActions()
        {
            bool busy = updateJob != null;
            string address = updateSource.Text.Trim();
            if (address.Length == 0) address = ProjectRepository;
            bool github = IsGithubRepository(address);
            updateSourceLabel.Text = releaseSourceMode == ReleaseSourceMode.Automatic ? "Automatic updates" :
                releaseSourceMode == ReleaseSourceMode.ManagedLocal ? "Local release server · starts on demand" :
                github ? "GitHub repository · latest stable release" :
                address.StartsWith("http://127.0.0.1", StringComparison.OrdinalIgnoreCase) ? "Local HTTP release server" :
                address.StartsWith("https://", StringComparison.OrdinalIgnoreCase) ? "HTTPS release server" : "Update manifest file";
            updateSourceHint.Visible = github;
            updateSourceHint.Text = github ? "Use a repository that publishes LiveTranslate releases. For a private repository, sign in to GitHub CLI (gh auth login) with an account that has read access." : "";
            if (releaseSourceMode == ReleaseSourceMode.Automatic)
                updateSourceHint.Text = "Checks GitHub first. If the release channel is empty or unavailable, shows the signed release bundled with this installation.";
            checkUpdates.Enabled = browseUpdate.Enabled = defaultUpdate.Enabled = githubUpdate.Enabled = automaticUpdate.Enabled = updateSource.Enabled = !busy;
            installUpdate.Enabled = !busy && offeredVersion != null && offeredDigest != null;
            installUpdate.Visible = offeredVersion != null && offeredDigest != null;
            cancelUpdate.Enabled = busy && !preparingUpdate && !restartCommitted;
            cancelUpdate.Visible = cancelUpdate.Enabled;
            updateActivity.Visible = busy;
            updateActivity.Style = busy ? ProgressBarStyle.Marquee : ProgressBarStyle.Blocks;
            updateActivity.MarqueeAnimationSpeed = busy ? 35 : 0;
        }

        private Task StartBundledFeed()
        {
            if (bundledFeedStartup == null) bundledFeedStartup = InitializeBundledFeed(sourceEditNumber);
            return bundledFeedStartup;
        }

        private async Task InitializeBundledFeed(int edits)
        {
            try
            {
                // Local-only. The helper checks the signed manifest and package
                // before recommending migration of a one-time release kit.
                var verified = await Task.Run(() => RunUpdateHelper(CancellationToken.None, "installed_feed.py"));
                string previous = Value(verified, "migrate_source");
                if (previous.Length != 0 && !closing && !IsDisposed && edits == sourceEditNumber &&
                    releaseSourceMode == ReleaseSourceMode.Custom &&
                    String.Equals(updateSource.Text, previous, StringComparison.OrdinalIgnoreCase) &&
                    String.Equals(File.ReadAllText(FeedPreference).Trim(), previous, StringComparison.OrdinalIgnoreCase))
                    SetReleaseSource(ProjectRepository, ReleaseSourceMode.Automatic);
            }
            catch (Exception) { } // An explicit check retries local verification and reports a failure.
        }

        private async void RunUpdateAction(bool install)
        {
            if (updateJob != null || closing || restartCommitted) return;
            if (install && (SetupRunning() || profileBusy))
            {
                updateState.Text = "Finish installing language components before restarting for an update.";
                return;
            }
            var job = new CancellationTokenSource();
            preparingUpdate = install;
            updateJob = job;
            RefreshUpdateActions();
            try
            {
                if (!install)
                {
                    updateState.Text = "Checking for updates.";
                    await StartBundledFeed();
                    job.Token.ThrowIfCancellationRequested();
                    if (closing || IsDisposed) return;
                }
                string source = NormalizedFeed(updateSource.Text);
                bool serveLocal = releaseSourceMode == ReleaseSourceMode.ManagedLocal;
                string installed = CurrentUpdateVersion();
                if (!install)
                {
                    offeredVersion = offeredDigest = null;
                    updateState.Text = "Checking for updates…";
                    var args = new List<string> { "check", "--feed", source, "--installed", installed };
                    if (releaseSourceMode == ReleaseSourceMode.Automatic) args.Add("--automatic");
                    var result = await Task.Run(() => UpdateCommand(job.Token, serveLocal, args.ToArray()));
                    job.Token.ThrowIfCancellationRequested();
                    if (closing || IsDisposed) return;
                    bool available;
                    if (!Boolean.TryParse(Value(result, "available"), out available))
                        throw new InvalidDataException("The updater returned an incomplete release check.");
                    if (Value(result, "status") == "bundled")
                        updateState.Text = BundledResult(result, installed);
                    else if (Value(result, "status") == "unpublished")
                        updateState.Text = "No stable release has been published to this GitHub repository. Installed version " + installed + ".";
                    else if (available)
                    {
                        string v = Value(result, "version"), digest = Value(result, "sha256");
                        Version next;
                        if (!Version.TryParse(v, out next) || digest.Length != 64)
                            throw new InvalidDataException("The release is missing its version or digest.");
                        long size; Int64.TryParse(Value(result, "size"), out size);
                        offeredVersion = v; offeredDigest = digest;
                        string downloadSize = size > 0 ? " (" + (size / 1048576.0).ToString("0.##", CultureInfo.CurrentCulture) + " MiB)" : "";
                        updateState.Text = (IsGithubRepository(source) ? "GitHub release v" : "Version ") + v + " is available" + downloadSize + ". Live translation will pause during restart.";
                    }
                    else if (Path.IsPathRooted(source))
                        updateState.Text = "This local feed has no newer release. Installed version " + installed + ".";
                    else updateState.Text = "You're up to date. Installed version " + installed + ".";
                    string cacheWarning = Value(result, "cache_warning");
                    if (!String.IsNullOrEmpty(cacheWarning))
                        updateState.Text += " The offline release copy could not be refreshed. " + cacheWarning;
                    try { SaveUpdateSource(FeedPreference, source, releaseSourceMode); }
                    catch (Exception) { updateState.Text += " The source could not be saved for next time."; }
                }
                else
                {
                    string version = offeredVersion, digest = offeredDigest;
                    if (version == null || digest == null) return;
                    updateState.Text = "Downloading and verifying version " + version + ". Keep the dashboard open until verification finishes.";
                    var result = await Task.Run(() => UpdateCommand(job.Token, serveLocal, "prepare", "--feed", source, "--installed", installed,
                        "--version", version, "--sha256", digest));
                    job.Token.ThrowIfCancellationRequested();
                    if (closing || IsDisposed) return;
                    if (SetupRunning() || profileBusy)
                        throw new InvalidOperationException("Component setup is active. Finish setup, then retry the update.");
                    string stage = Value(result, "stage");
                    if (stage.Length != 32 || stage.Trim("0123456789abcdef".ToCharArray()).Length != 0 || Value(result, "version") != version)
                        throw new InvalidDataException("The prepared update did not match the selected release.");
                    updateState.Text = "Preparing to restart…";
                    preparingUpdate = false;
                    waitingForInstaller = true;
                    RefreshUpdateActions();
                    int parent;
                    using (Process current = Process.GetCurrentProcess()) parent = current.Id;
                    using (Process handoff = await Task.Run(() => AwaitUpdateHandoff(stage, parent, job.Token)))
                    {
                        if (IsDisposed || closing) return; // The ready installer can finish during a requested shutdown.
                        if (job.IsCancellationRequested || SetupRunning() || profileBusy)
                        {
                            StopUpdateHelper(handoff);
                            job.Token.ThrowIfCancellationRequested();
                            throw new InvalidOperationException("Component setup is active. Finish setup, then retry the update.");
                        }
                        restartCommitted = true;
                        settingsForm.Hide();
                        Close();
                        if (!closing && !IsDisposed)
                        {
                            StopUpdateHelper(handoff);
                            restartCommitted = false;
                            throw new InvalidOperationException("The dashboard is busy. Retry when component setup finishes.");
                        }
                    }
                }
            }
            catch (OperationCanceledException) { if (!closing && !IsDisposed) updateState.Text = "Update canceled."; }
            catch (Exception ex) { if (!closing && !IsDisposed) updateState.Text = "Update could not finish. " + ex.Message; }
            finally
            {
                preparingUpdate = false;
                waitingForInstaller = false;
                updateJob = null;
                job.Dispose();
                if (!closing && !IsDisposed) RefreshUpdateActions();
            }
        }

        private static string BundledResult(Dictionary<string, object> result, string installed)
        {
            Version version;
            string release = Value(result, "version"), github = Value(result, "github_status");
            if (!Version.TryParse(release, out version) || (github != "unavailable" && github != "unpublished") ||
                !Object.Equals(result["available"], false))
                throw new InvalidDataException("The updater returned an incomplete bundled release check.");
            string verified = "Verified bundled release " + release + ". Installed version " + installed + ". ";
            return verified + (github == "unpublished" ? "GitHub has no published stable release." :
                "GitHub could not be checked for newer releases. " + Value(result, "github_detail"));
        }

        private static string QuoteUpdateArgument(string value)
        {
            var b = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in value)
            {
                if (c == '\\') { ++slashes; continue; }
                if (c == '"') b.Append('\\', 2 * slashes + 1);
                else b.Append('\\', slashes);
                b.Append(c);
                slashes = 0;
            }
            return b.Append('\\', 2 * slashes).Append('"').ToString();
        }

        private static Process StartUpdateHelper(string script, params string[] args)
        {
            string python = Path.Combine(UpdateRoot, "runtime", "python.exe");
            string helper = Path.Combine(UpdateRoot, "backend", script);
            if (!File.Exists(python) || !File.Exists(helper)) throw new FileNotFoundException("The updater is incomplete. Run the one-time updater setup.");
            var cli = new StringBuilder("-I -B -u -X utf8 ").Append(QuoteUpdateArgument(helper));
            foreach (string arg in args) cli.Append(' ').Append(QuoteUpdateArgument(arg));
            var start = new ProcessStartInfo(python, cli.ToString()) {
                WorkingDirectory = UpdateRoot, UseShellExecute = false, CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
            return Process.Start(start);
        }

        private static void StopUpdateHelper(Process process)
        {
            try { if (!process.HasExited) process.Kill(); }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception) { }
        }

        private static Dictionary<string, object> UpdateCommand(CancellationToken token, bool serveLocal, params string[] args)
        {
            token.ThrowIfCancellationRequested();
            if (serveLocal)
            {
                var serverArgs = new List<string>(args);
                serverArgs.Add("--serve-local");
                args = serverArgs.ToArray();
            }
            return RunUpdateHelper(token, "app_updates.py", args);
        }

        private static Dictionary<string, object> RunUpdateHelper(CancellationToken token, string script, params string[] args)
        {
            token.ThrowIfCancellationRequested();
            using (Process p = StartUpdateHelper(script, args))
            using (token.Register(() => StopUpdateHelper(p)))
            {
                Task<string> output = p.StandardOutput.ReadToEndAsync();
                Task<string> errors = p.StandardError.ReadToEndAsync();
                p.WaitForExit();
                token.ThrowIfCancellationRequested();
                string stdout = output.GetAwaiter().GetResult();
                string stderr = errors.GetAwaiter().GetResult();
                Dictionary<string, object> reply = null;
                try { reply = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(stdout); }
                catch (ArgumentException) { }
                catch (InvalidOperationException) { }
                if (p.ExitCode != 0 || reply == null || !Object.Equals(true, reply.ContainsKey("ok") ? reply["ok"] : null))
                {
                    string message = reply == null ? "" : Value(reply, "error");
                    if (String.IsNullOrWhiteSpace(message)) message = String.IsNullOrWhiteSpace(stderr) ?
                        "The update helper did not return a release result." : stderr.Trim();
                    throw new InvalidOperationException(message.Length > 500 ? message.Substring(0, 500) : message);
                }
                return reply;
            }
        }

        private static Process AwaitUpdateHandoff(string stage, int parent, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            Process p = StartUpdateHelper("update_install.py", "apply", "--stage", stage,
                "--parent", parent.ToString(CultureInfo.InvariantCulture));
            try
            {
                using (token.Register(() => StopUpdateHelper(p)))
                {
                    Task<string> line = p.StandardOutput.ReadLineAsync();
                    Task<string> errors = p.StandardError.ReadToEndAsync();
                    if (!line.Wait(TimeSpan.FromMinutes(10)))
                        throw new TimeoutException("The installer did not become ready. You can retry the update.");
                    token.ThrowIfCancellationRequested();
                    string response = line.GetAwaiter().GetResult();
                    if (response != "READY")
                    {
                        string detail = !String.IsNullOrWhiteSpace(response) ? response :
                            (errors.Wait(1000) ? errors.Result.Trim() : "");
                        if (detail.Length > 500) detail = detail.Substring(0, 500);
                        throw new InvalidOperationException(detail.Length != 0 ? detail : "The installer could not start.");
                    }
                }
                return p;
            }
            catch
            {
                StopUpdateHelper(p);
                p.Dispose();
                throw;
            }
        }
    }
}
