using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace LiveTranslate.Setup
{
    internal sealed class SetupWindow : Form
    {
        private readonly BackgroundWorker installer = new BackgroundWorker();
        private readonly Label heading = new Label();
        private readonly TextBox status = new TextBox();
        private readonly ProgressBar progress = new ProgressBar();
        private readonly Button primary = new Button();
        private readonly Button close = new Button();
        private readonly Font headingFont;
        private readonly Icon setupIcon;
        private bool installed;
        private bool working;

        public SetupWindow()
        {
            Text = "LiveTranslate Setup";
            Font = SystemFonts.MessageBoxFont;
            AutoScaleDimensions = new SizeF(96F, 96F);
            AutoScaleMode = AutoScaleMode.Dpi;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(520, 270);
            MinimumSize = SizeFromClientSize(new Size(420, 250));
            MaximizeBox = false;
            BackColor = SystemColors.Window;
            ForeColor = SystemColors.WindowText;
            setupIcon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            if (setupIcon != null)
                Icon = setupIcon;

            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.Padding = new Padding(24, 18, 24, 16);
            layout.ColumnCount = 1;
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
            layout.RowCount = 5;
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            Controls.Add(layout);

            headingFont = new Font(Font.FontFamily, 18F, FontStyle.Bold);
            heading.Font = headingFont;
            heading.Text = "Install LiveTranslate";
            heading.AutoSize = true;
            heading.Margin = Padding.Empty;
            layout.Controls.Add(heading, 0, 0);

            Label version = new Label();
            version.AutoSize = true;
            version.Text = "Version " + Application.ProductVersion + "  |  Windows x64";
            version.Margin = new Padding(1, 3, 0, 13);
            layout.Controls.Add(version, 0, 1);

            status.Text = "Install LiveTranslate for your Windows account. Setup includes the offline runtime and starter language models.";
            status.AccessibleName = "Setup status";
            status.Multiline = true;
            status.ReadOnly = true;
            status.BorderStyle = BorderStyle.None;
            status.BackColor = SystemColors.Window;
            status.ForeColor = SystemColors.WindowText;
            status.ScrollBars = ScrollBars.None;
            status.Dock = DockStyle.Fill;
            status.Margin = new Padding(1, 0, 1, 0);
            status.TabIndex = 1;
            layout.Controls.Add(status, 0, 2);

            progress.AccessibleName = "Installation in progress";
            progress.Style = ProgressBarStyle.Marquee;
            progress.MarqueeAnimationSpeed = 0;
            progress.Height = 7;
            progress.Dock = DockStyle.Top;
            progress.Margin = new Padding(1, 4, 1, 0);
            progress.Visible = false;
            layout.Controls.Add(progress, 0, 3);

            FlowLayoutPanel actions = new FlowLayoutPanel();
            actions.AutoSize = true;
            actions.Dock = DockStyle.Fill;
            actions.FlowDirection = FlowDirection.RightToLeft;
            actions.WrapContents = false;
            actions.Margin = new Padding(0, 12, 0, 0);
            actions.TabIndex = 0;
            layout.Controls.Add(actions, 0, 4);

            close.Text = "&Cancel";
            close.AutoSize = true;
            close.MinimumSize = new Size(86, 30);
            close.Margin = new Padding(8, 0, 0, 0);
            close.TabIndex = 1;
            close.Click += delegate { Close(); };
            actions.Controls.Add(close);

            primary.Text = "&Install";
            primary.AutoSize = true;
            primary.MinimumSize = new Size(92, 30);
            primary.Margin = Padding.Empty;
            primary.TabIndex = 0;
            primary.Click += PrimaryClicked;
            actions.Controls.Add(primary);
            AcceptButton = primary;
            CancelButton = close;
            Shown += delegate { primary.Focus(); };

            installer.WorkerReportsProgress = true;
            installer.DoWork += delegate
            {
                SetupPayload.Install(delegate(string message) { installer.ReportProgress(0, message); });
            };
            installer.ProgressChanged += delegate(object sender, ProgressChangedEventArgs args)
            {
                status.Text = (string)args.UserState;
            };
            installer.RunWorkerCompleted += InstallationFinished;
        }

        private void PrimaryClicked(object sender, EventArgs args)
        {
            if (installed)
            {
                LaunchInstalledApp();
                return;
            }

            if (working)
                return;

            working = true;
            heading.Text = "Installing LiveTranslate";
            status.ScrollBars = ScrollBars.None;
            status.Text = "Preparing your installation...";
            primary.Enabled = false;
            close.Enabled = false;
            progress.Visible = true;
            progress.MarqueeAnimationSpeed = 28;
            installer.RunWorkerAsync();
        }

        private void InstallationFinished(object sender, RunWorkerCompletedEventArgs args)
        {
            working = false;
            progress.MarqueeAnimationSpeed = 0;
            progress.Visible = false;
            close.Enabled = true;
            close.Text = "&Close";
            primary.Enabled = true;
            if (args.Error != null)
            {
                heading.Text = "Setup could not finish";
                status.ScrollBars = ScrollBars.Vertical;
                status.Text = args.Error.Message;
                primary.Text = "&Try again";
            }
            else
            {
                installed = true;
                heading.Text = "LiveTranslate is installed";
                status.Text = "Open LiveTranslate now or find it in your Start menu later.";
                primary.Text = "&Open LiveTranslate";
            }
            primary.Focus();
        }

        private void LaunchInstalledApp()
        {
            string shortcut = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),
                                           "LiveTranslate", "LiveTranslate.lnk");
            try
            {
                if (!File.Exists(shortcut))
                    throw new FileNotFoundException("The LiveTranslate Start menu shortcut could not be found.");
                ProcessStartInfo start = new ProcessStartInfo(shortcut);
                start.UseShellExecute = true;
                using (Process launched = Process.Start(start)) { }
                Close();
            }
            catch (Exception error)
            {
                status.ScrollBars = ScrollBars.Vertical;
                status.Text = "Windows could not open LiveTranslate. " + error.Message;
            }
        }

        protected override void OnFormClosing(FormClosingEventArgs args)
        {
            base.OnFormClosing(args);
            if (working)
                args.Cancel = true;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                installer.Dispose();
                headingFont.Dispose();
                if (setupIcon != null)
                    setupIcon.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
