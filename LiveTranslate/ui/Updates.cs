using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed partial class MainForm
    {
        private Label updateState, updateSourceLabel, updateSourceHint;
        private bool preparingUpdate, waitingForInstaller;
        private Button checkUpdates, installUpdate, cancelUpdate;
        private ProgressBar updateActivity;
        private CancellationTokenSource updateJob;
        private string offeredVersion, offeredDigest;
        private bool restartCommitted;
        private const string ProjectRepository = "https://github.com/tokinmew/LiveTranslate";

        private static string UpdateRoot { get { return AppDomain.CurrentDomain.BaseDirectory; } }

        private static string CurrentUpdateVersion()
        {
            Version v = typeof(MainForm).Assembly.GetName().Version;
            return v.Revision > 0 ? v.ToString(4) : v.ToString(3);
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
            return "Check for the latest release on GitHub.";
        }

        private void BuildUpdatesTab()
        {
            var page = SettingsPage("Updates");
            var layout = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
                ColumnCount = 1, Margin = Padding.Empty, BackColor = SystemColors.Window, ForeColor = paperInk };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            updateSourceLabel = new Label { Text = "GitHub Releases · latest stable release", AutoSize = true,
                Font = new Font(Font, FontStyle.Bold), Margin = new Padding(0, 0, 0, 6) };
            layout.Controls.Add(updateSourceLabel, 0, 0);
            var repository = new Label { Text = ProjectRepository, AutoSize = true, ForeColor = ink,
                AccessibleName = "Official update repository", Margin = new Padding(0, 0, 0, 6) };
            layout.Controls.Add(repository, 0, 1);
            updateSourceHint = new Label { Text = "Checks the latest published LiveTranslate release on GitHub. Updates are verified before installation, and your models and settings stay installed.",
                AutoSize = true, MaximumSize = new Size(525, 0), ForeColor = ink, Margin = new Padding(0, 6, 0, 0) };
            layout.Controls.Add(updateSourceHint, 0, 2);
            updateState = new Label { Text = LastUpdateResult(), AutoSize = true,
                MaximumSize = new Size(540, 0), ForeColor = ink, Margin = new Padding(0, 16, 0, 6) };
            updateState.AccessibleRole = AccessibleRole.StatusBar;
            layout.Controls.Add(updateState, 0, 3);
            layout.SizeChanged += delegate
            {
                int width = Math.Max(1, layout.ClientSize.Width - 4);
                repository.MaximumSize = updateSourceHint.MaximumSize = updateState.MaximumSize = new Size(width, 0);
            };
            updateActivity = new ProgressBar { Dock = DockStyle.Top, Height = 6, MarqueeAnimationSpeed = 0,
                Style = ProgressBarStyle.Blocks, Margin = new Padding(0, 2, 0, 8) };
            layout.Controls.Add(updateActivity, 0, 4);
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
            layout.Controls.Add(actions, 0, 5);
            AddSettingsBody(page, "App updates", "Installed version " + CurrentUpdateVersion() + ". Check for an official GitHub release.", layout, 0);
            settingsTabs.TabPages.Add(page);
            FormClosed += delegate { if (updateJob != null && !preparingUpdate && !restartCommitted && !waitingForInstaller) updateJob.Cancel(); };
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
            checkUpdates.Enabled = !busy;
            installUpdate.Enabled = !busy && offeredVersion != null && offeredDigest != null;
            installUpdate.Visible = offeredVersion != null && offeredDigest != null;
            cancelUpdate.Enabled = busy && !preparingUpdate && !restartCommitted;
            cancelUpdate.Visible = cancelUpdate.Enabled;
            updateActivity.Visible = busy;
            updateActivity.Style = busy ? ProgressBarStyle.Marquee : ProgressBarStyle.Blocks;
            updateActivity.MarqueeAnimationSpeed = busy ? 35 : 0;
        }

        private async void RunUpdateAction(bool install)
        {
            if (updateJob != null || closing || restartCommitted) return;
            if (install && (SetupRunning() || profileBusy))
            {
                updateState.Text = "Finish installing language components before restarting for an update.";
                return;
            }
            if (!install) offeredVersion = offeredDigest = null;
            var job = new CancellationTokenSource();
            preparingUpdate = install;
            updateJob = job;
            RefreshUpdateActions();
            try
            {
                string installed = CurrentUpdateVersion();
                if (!install)
                {
                    updateState.Text = "Checking GitHub for updates…";
                    var result = await Task.Run(() => UpdateCommand(job.Token, "check", "--installed", installed));
                    job.Token.ThrowIfCancellationRequested();
                    if (closing || IsDisposed) return;
                    bool available;
                    if (!Boolean.TryParse(Value(result, "available"), out available))
                        throw new InvalidDataException("GitHub did not return a complete release check.");
                    string status = Value(result, "status");
                    if (status == "unpublished" && !available)
                        updateState.Text = "No stable release has been published to the LiveTranslate GitHub repository. Installed version " + installed + ".";
                    else
                    {
                        string v = Value(result, "version"), digest = Value(result, "sha256");
                        Version next, current;
                        if ((status.Length != 0 && status != "available" && status != "current") || !Version.TryParse(v, out next) ||
                            !Version.TryParse(installed, out current) || available != (next > current))
                            throw new InvalidDataException("GitHub did not return a valid stable release version.");
                        if (available)
                        {
                            if (digest.Length != 64 || digest.Trim("0123456789abcdef".ToCharArray()).Length != 0)
                                throw new InvalidDataException("The GitHub release is missing its verified digest.");
                            long size; Int64.TryParse(Value(result, "size"), out size);
                            offeredVersion = v; offeredDigest = digest;
                            string downloadSize = size > 0 ? " (" + (size / 1048576.0).ToString("0.##", CultureInfo.CurrentCulture) + " MiB)" : "";
                            updateState.Text = "GitHub release v" + v + " is available" + downloadSize + ". Live translation will pause during restart.";
                        }
                        else updateState.Text = "You're up to date with GitHub. Installed version " + installed + ".";
                    }
                }
                else
                {
                    string version = offeredVersion, digest = offeredDigest;
                    if (version == null || digest == null) return;
                    updateState.Text = "Downloading and verifying version " + version + ". Keep the dashboard open until verification finishes.";
                    var result = await Task.Run(() => UpdateCommand(job.Token, "prepare", "--installed", installed,
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
            catch (OperationCanceledException)
            {
                offeredVersion = offeredDigest = null;
                if (!closing && !IsDisposed) updateState.Text = "Update canceled.";
            }
            catch (Exception ex)
            {
                offeredVersion = offeredDigest = null;
                if (!closing && !IsDisposed) updateState.Text = "GitHub update could not finish. " + ex.Message;
            }
            finally
            {
                preparingUpdate = false;
                waitingForInstaller = false;
                updateJob = null;
                job.Dispose();
                if (!closing && !IsDisposed) RefreshUpdateActions();
            }
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

        private static Dictionary<string, object> UpdateCommand(CancellationToken token, params string[] args)
        {
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
