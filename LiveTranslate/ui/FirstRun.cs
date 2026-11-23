using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal static class FirstRun
    {
        private static readonly string[] TextPacks = { "zh", "zt", "ja", "ko" };
        private static readonly string[] SpeechFiles = { "model.bin", "config.json", "tokenizer.json", "vocabulary.txt" };
        private static readonly string[] OcrPacks = { "chi_sim", "chi_tra", "jpn", "jpn_vert", "kor" };

        internal static bool EnsureReady(string root)
        {
            // The online/developer edition starts its dashboard before optional model setup.
            if (!Directory.Exists(Path.Combine(root, "payload")) || IsReady(root)) return true;
            using (var window = new PreparationWindow(root))
                return window.ShowDialog() == DialogResult.OK;
        }

        internal static bool IsReady(string root)
        {
            if (!File.Exists(Path.Combine(root, "LiveTranslate.exe")) ||
                !File.Exists(Path.Combine(root, "runtime", "python.exe")) ||
                !File.Exists(Path.Combine(root, "runtime", "ready.txt")) ||
                !File.Exists(Path.Combine(root, "model-test-results", "offline-43c2c21bc9c17193.ok")))
                return false;
            foreach (string pack in TextPacks)
                if (!File.Exists(Path.Combine(root, "data", "text-packs", pack + "_en", "model", "model.bin")))
                    return false;
            foreach (string file in SpeechFiles)
                if (!File.Exists(Path.Combine(root, "data", "speech", "base", file)))
                    return false;
            foreach (string pack in OcrPacks)
                if (!File.Exists(Path.Combine(root, "data", "tessdata", pack + ".traineddata")))
                    return false;
            return true;
        }

        internal static void Prepare(string root, Action<string> progress)
        {
            string script = Path.Combine(root, "scripts", "Prepare-Offline.ps1");
            if (!File.Exists(script))
                throw new FileNotFoundException("The offline preparation files are missing. Run setup again to repair them.");
            var start = new ProcessStartInfo {
                FileName = Path.Combine(Environment.SystemDirectory, @"WindowsPowerShell\v1.0\powershell.exe"),
                WorkingDirectory = root,
                Arguments = "-NoLogo -NoProfile -STA -NonInteractive -ExecutionPolicy RemoteSigned -File \"" + script + "\"",
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true
            };
            start.EnvironmentVariables.Remove("PSModulePath");
            using (var process = new Process())
            {
                string lastError = null;
                process.StartInfo = start;
                process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs args)
                {
                    if (!String.IsNullOrWhiteSpace(args.Data))
                    {
                        string line = args.Data.Trim();
                        lastError = line.Substring(0, Math.Min(500, line.Length));
                    }
                };
                process.Start();
                process.BeginErrorReadLine();
                string output;
                while ((output = process.StandardOutput.ReadLine()) != null)
                {
                    if (output.StartsWith("Unpacking the Windows runtime", StringComparison.Ordinal))
                        progress("Unpacking the offline runtime...");
                    else if (output.StartsWith("Preparing the 13 original language files", StringComparison.Ordinal))
                        progress("Preparing and testing the included language models...");
                }
                process.WaitForExit();
                if (process.ExitCode != 0)
                    throw new IOException(lastError ?? "Offline preparation stopped. Open LiveTranslate again to retry.");
            }
            if (!IsReady(root))
                throw new InvalidDataException("The required runtime or language files are missing after preparation. Run setup to repair the installation.");
        }

        private sealed class PreparationWindow : Form
        {
            private readonly BackgroundWorker worker = new BackgroundWorker();
            private bool active = true;

            internal PreparationWindow(string root)
            {
                Text = "Preparing LiveTranslate";
                Font = SystemFonts.MessageBoxFont;
                StartPosition = FormStartPosition.CenterScreen;
                AutoScaleDimensions = new SizeF(96, 96);
                AutoScaleMode = AutoScaleMode.Dpi;
                ClientSize = new Size(450, 160);
                MinimumSize = SizeFromClientSize(new Size(370, 150));
                MaximizeBox = false;
                var layout = new TableLayoutPanel {
                    Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3, Padding = new Padding(18)
                };
                layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
                layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
                layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                Controls.Add(layout);
                var status = new TextBox {
                    Text = "Checking the offline files. LiveTranslate will open when preparation finishes.",
                    AccessibleName = "Preparation status", BorderStyle = BorderStyle.None,
                    BackColor = SystemColors.Control, ForeColor = SystemColors.ControlText,
                    Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, Margin = Padding.Empty
                };
                layout.Controls.Add(status, 0, 0);
                var bar = new ProgressBar {
                    AccessibleName = "Preparation in progress", Style = ProgressBarStyle.Marquee,
                    MarqueeAnimationSpeed = 30, Dock = DockStyle.Top, Height = 9
                };
                layout.Controls.Add(bar, 0, 1);
                var close = new Button {
                    Text = "&Close", AutoSize = true, Anchor = AnchorStyles.Right, Visible = false
                };
                layout.Controls.Add(close, 0, 2);
                close.Click += delegate { DialogResult = DialogResult.Cancel; Close(); };
                worker.WorkerReportsProgress = true;
                worker.DoWork += delegate {
                    Prepare(root, delegate(string message) { worker.ReportProgress(0, message); });
                };
                worker.ProgressChanged += delegate(object sender, ProgressChangedEventArgs args) {
                    status.Text = (string)args.UserState;
                };
                worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs args) {
                    active = false;
                    if (args.Error == null)
                    {
                        DialogResult = DialogResult.OK;
                        Close();
                        return;
                    }
                    Text = "LiveTranslate could not finish preparation";
                    bar.Visible = false;
                    status.ScrollBars = ScrollBars.Vertical;
                    status.Text = args.Error.Message;
                    close.Visible = true;
                    AcceptButton = close;
                    CancelButton = close;
                    close.Focus();
                };
                Shown += delegate { worker.RunWorkerAsync(); };
            }

            protected override void OnFormClosing(FormClosingEventArgs args)
            {
                base.OnFormClosing(args);
                if (active) args.Cancel = true;
            }

            protected override void Dispose(bool disposing)
            {
                if (disposing) worker.Dispose();
                base.Dispose(disposing);
            }
        }
    }
}
