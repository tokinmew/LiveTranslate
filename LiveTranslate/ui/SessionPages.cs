using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class SessionNavigationButton : Button
    {
        internal WorkspaceGlyph.Kind Symbol;
        internal bool SelectedPage;
        internal SessionNavigationButton()
        {
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            UseVisualStyleBackColor = false;
            Cursor = Cursors.Hand;
            AccessibleRole = AccessibleRole.PageTab;
            TabStop = true;
            SetStyle(ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        }
        protected override void OnPaint(PaintEventArgs e)
        {
            Control surround = Parent;
            while (surround != null && surround.BackColor.A != 255) surround = surround.Parent;
            e.Graphics.Clear(surround == null ? BackColor : surround.BackColor);
            float scale = e.Graphics.DpiX / 96F;
            RectangleF bounds = new RectangleF(0, 1, Width - 1, Height - 3);
            using (var path = ModernGeometry.Rounded(bounds, 9 * scale))
            using (var fill = new SolidBrush(SelectedPage ? Color.FromArgb(29, 71, 67) : BackColor))
                e.Graphics.FillPath(fill, path);
            Color color = SelectedPage ? Color.FromArgb(75, 231, 201) : ForeColor;
            WorkspaceGlyph.Draw(e.Graphics, new RectangleF(14 * scale, (Height - 21 * scale) / 2, 21 * scale, 21 * scale), Symbol, color);
            Rectangle text = new Rectangle((int)(47 * scale), 0, Math.Max(1, Width - (int)(56 * scale)), Height);
            TextRenderer.DrawText(e.Graphics, Text, Font, text, ForeColor,
                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -4, -5), color, BackColor);
        }
    }

    internal sealed partial class MainForm
    {
        private readonly Dictionary<string, Panel> sessionPages = new Dictionary<string, Panel>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, SessionNavigationButton> sessionNavigation = new Dictionary<string, SessionNavigationButton>(StringComparer.OrdinalIgnoreCase);
        private Panel sessionPageHost, liveTranscriptSlot, historyTranscriptSlot;
        private ModernCard sessionTranscriptCard, sessionCaptureDetails;
        private TableLayoutPanel sessionLiveLayout;
        private WorkspaceGlyph sessionBrand;
        private Label sessionPageTitle, sessionPageDescription, sessionStatePill, sessionTranscriptTitle;
        private Label sessionAudioDescription, sessionSettingsSummary, sessionAudioSourceTitle;
        private Button sessionAudioSummary, sessionAudioLanguage, sessionDetailsButton;
        private Button sessionPauseButton, sessionEndButton, sessionCaptionButton, sessionSaveButton, historySaveButton;
        private Button sessionSystemMode, sessionMicMode, sessionBothMode;
        private bool sessionDetailsOpen, sessionPaused, resumeSessionAudio, resumeSessionScreen, changingSessionState;
        private string activeSessionPage = "live";

        internal bool SessionPaused { get { return sessionPaused; } }
        internal string SessionPauseLabel { get { return sessionPaused ? "Resume translation" : "Pause translation"; } }
        internal bool SessionCanPause { get { return !closing && !SetupRunning() && !profileBusy &&
            (sessionPaused || audioWanted || screenWanted || screenArmed || oneShotPending); } }
        internal string SessionStatusText
        {
            get
            {
                if (sessionPaused && oneShotPending) return "Reading screen";
                if (sessionPaused) return "Paused";
                if (SetupRunning()) return "Preparing components";
                if (!connected) return "Engine unavailable";
                if (audioWanted)
                {
                    string detail = audioStateLabel == null ? "" : audioStateLabel.Text;
                    return detail.StartsWith("Starting", StringComparison.OrdinalIgnoreCase) || detail.StartsWith("Opening", StringComparison.OrdinalIgnoreCase)
                        ? "Starting audio" : "Listening";
                }
                if (screenWanted) return "Watching screen";
                if (oneShotPending) return "Reading screen";
                if (screenArmed) return "Screen waiting";
                return "Idle";
            }
        }

        private void BuildSessionWorkspace()
        {
            TableLayoutPanel shell = Columns(210, 0);
            shell.BackColor = background;
            Controls.Add(shell);
            shell.Controls.Add(BuildSessionNavigation(), 0, 0);
            TableLayoutPanel body = Rows(92, 0, 38);
            body.Padding = new Padding(25, 9, 25, 0);
            shell.Controls.Add(body, 1, 0);
            TableLayoutPanel header = Columns(0, 192);
            TableLayoutPanel captions = Rows(49, 0);
            sessionPageTitle = Title("Live translation", paperInk, 25F);
            sessionPageDescription = Note("Follow the conversation as it happens.", secondaryInk);
            sessionPageDescription.Font = new Font(Font.FontFamily, 11F);
            captions.Controls.Add(sessionPageTitle, 0, 0);
            captions.Controls.Add(sessionPageDescription, 0, 1);
            header.Controls.Add(captions, 0, 0);
            ModernCard pill = LightCard(field, new Padding(10, 0, 10, 0));
            pill.BorderColor = accent;
            pill.Margin = new Padding(8, 15, 0, 23);
            sessionStatePill = Note("Engine unavailable", accent);
            sessionStatePill.TextAlign = ContentAlignment.MiddleCenter;
            sessionStatePill.Font = new Font(Font.FontFamily, 10F, FontStyle.Bold);
            sessionStatePill.AccessibleRole = AccessibleRole.StatusBar;
            pill.Controls.Add(sessionStatePill);
            header.Controls.Add(pill, 1, 0);
            body.Controls.Add(header, 0, 0);
            sessionPageHost = new Panel { Dock = DockStyle.Fill, Margin = Padding.Empty, BackColor = background };
            body.Controls.Add(sessionPageHost, 0, 1);
            BuildLiveSessionPage();
            BuildHistorySessionPage();
            BuildAudioSessionPage();
            BuildSettingsSessionPage();
            TableLayoutPanel footer = Columns(0, 162);
            footer.Padding = new Padding(0, 4, 0, 0);
            status = Note("Checking local language files…", secondaryInk);
            status.Font = new Font(Font.FontFamily, 9F);
            status.AccessibleRole = AccessibleRole.StatusBar;
            footer.Controls.Add(status, 0, 0);
            Button settings = SessionButton("Translation settings", delegate { OpenSettings(); }, false);
            settings.Font = new Font(Font.FontFamily, 8.8F);
            footer.Controls.Add(settings, 1, 0);
            body.Controls.Add(footer, 0, 2);
            shell.SizeChanged += delegate {
                float scale = SessionScale();
                shell.ColumnStyles[0].Width = (shell.ClientSize.Width < 1050 * scale ? 184 : 210) * scale;
                LayoutSessionPage();
            };
            ShowSessionPage("live");
        }

        private Control BuildSessionNavigation()
        {
            Panel rail = new Panel { Dock = DockStyle.Fill, BackColor = surface, Padding = new Padding(12, 20, 12, 16), Margin = Padding.Empty };
            TableLayoutPanel layout = Rows(77, 0, 102);
            layout.BackColor = surface;
            TableLayoutPanel brand = Columns(34, 0);
            sessionBrand = new WorkspaceGlyph { Symbol = WorkspaceGlyph.Kind.Brand, ForeColor = accent,
                Size = new Size(27, 27), Anchor = AnchorStyles.Left, Margin = Padding.Empty };
            brand.Controls.Add(sessionBrand, 0, 0);
            brand.Controls.Add(Title("LiveTranslate", paperInk, 13F), 1, 0);
            layout.Controls.Add(brand, 0, 0);
            TableLayoutPanel navigation = Rows(47, 47, 47, 47, 0);
            AddSessionNavigation(navigation, 0, "live", "Live session", WorkspaceGlyph.Kind.Live);
            AddSessionNavigation(navigation, 1, "history", "Session history", WorkspaceGlyph.Kind.History);
            AddSessionNavigation(navigation, 2, "audio", "Audio setup", WorkspaceGlyph.Kind.Audio);
            AddSessionNavigation(navigation, 3, "settings", "Settings", WorkspaceGlyph.Kind.Settings);
            layout.Controls.Add(navigation, 0, 1);
            TableLayoutPanel foot = Rows(1, 42, 0);
            foot.Controls.Add(Divider(border), 0, 0);
            engineBadge = new EngineIndicator { Text = "Checking local engine", Dock = DockStyle.Fill, ForeColor = secondaryInk,
                Font = new Font(Font.FontFamily, 8.4F), Margin = Padding.Empty };
            foot.Controls.Add(engineBadge, 0, 1);
            Label local = Note("Translation stays on this PC.\nSession captions are not saved automatically.", secondaryInk);
            local.Font = new Font(Font.FontFamily, 8.3F);
            local.TextAlign = ContentAlignment.TopLeft;
            foot.Controls.Add(local, 0, 2);
            layout.Controls.Add(foot, 0, 2);
            rail.Controls.Add(layout);
            return rail;
        }

        private void AddSessionNavigation(TableLayoutPanel parent, int row, string page, string text, WorkspaceGlyph.Kind symbol)
        {
            SessionNavigationButton button = new SessionNavigationButton { Text = text, Symbol = symbol,
                Dock = DockStyle.Fill, BackColor = surface, ForeColor = paperInk, Font = new Font(Font.FontFamily, 10F),
                Margin = new Padding(0, 2, 0, 3), AccessibleName = text, AccessibleDescription = "Open " + text.ToLowerInvariant() };
            button.Click += delegate { ShowSessionPage(page); };
            sessionNavigation.Add(page, button);
            parent.Controls.Add(button, 0, row);
        }

        private Panel AddSessionPage(string key)
        {
            Panel page = new Panel { Dock = DockStyle.Fill, BackColor = background, AutoScroll = true,
                Margin = Padding.Empty, Visible = false, AccessibleName = key + " page" };
            sessionPages.Add(key, page);
            sessionPageHost.Controls.Add(page);
            return page;
        }

        private void BuildLiveSessionPage()
        {
            Panel page = AddSessionPage("live");
            sessionLiveLayout = Rows(137, 0, 0, 58, 151);
            sessionLiveLayout.Dock = DockStyle.Top;
            sessionLiveLayout.Controls.Add(BuildCapturePanel(), 0, 0);
            sessionCaptureDetails = BuildSessionCaptureDetails();
            sessionCaptureDetails.Visible = false;
            sessionLiveLayout.Controls.Add(sessionCaptureDetails, 0, 1);
            liveTranscriptSlot = new Panel { Dock = DockStyle.Fill, Margin = new Padding(0, 12, 0, 0) };
            sessionTranscriptCard = BuildTranscript();
            liveTranscriptSlot.Controls.Add(sessionTranscriptCard);
            sessionLiveLayout.Controls.Add(liveTranscriptSlot, 0, 2);
            TableLayoutPanel actions = Columns(0, 158);
            actions.Padding = new Padding(0, 10, 0, 6);
            FlowLayoutPanel primary = Flow();
            sessionPauseButton = SessionButton("Pause translation", delegate { ToggleSessionPause(); }, true);
            sessionPauseButton.Width = 183;
            sessionEndButton = SessionButton("End session", delegate { EndSession(); }, false);
            sessionEndButton.Width = 132;
            Button captions = sessionCaptionButton = SessionButton("Open captions", delegate { ShowCaptionOptions(); }, false);
            captions.Width = 127;
            foreach (Button button in new[] { sessionPauseButton, sessionEndButton, captions })
            {
                button.Dock = DockStyle.None;
                button.Height = 38;
                button.AutoSize = false;
            }
            primary.Controls.Add(sessionPauseButton);
            primary.Controls.Add(sessionEndButton);
            primary.Controls.Add(captions);
            actions.Controls.Add(primary, 0, 0);
            sessionSaveButton = SessionButton("Save transcript", delegate { SaveTranscriptFile(); }, false);
            sessionSaveButton.Margin = Padding.Empty;
            actions.Controls.Add(sessionSaveButton, 1, 0);
            sessionLiveLayout.Controls.Add(actions, 0, 3);
            sessionLiveLayout.Controls.Add(BuildComposer(), 0, 4);
            page.Controls.Add(sessionLiveLayout);
            page.SizeChanged += delegate { LayoutSessionPage(); };
        }

        private ModernCard BuildSessionCaptureDetails()
        {
            ModernCard card = LightCard(paper, new Padding(14, 7, 14, 7));
            card.Margin = new Padding(0, 8, 0, 0);
            TableLayoutPanel content = Rows(31, 30, 0);
            TableLayoutPanel heading = Columns(0, 175);
            profileReadiness = Title("Language files", paperInk, 10F);
            heading.Controls.Add(profileReadiness, 0, 0);
            setupProfile = SessionButton("Manage language files", SetupSelected, false);
            setupProfile.Font = new Font(Font.FontFamily, 8.5F);
            heading.Controls.Add(setupProfile, 1, 0);
            content.Controls.Add(heading, 0, 0);
            profileHint = Note("", secondaryInk);
            profileHint.Font = new Font(Font.FontFamily, 9F);
            content.Controls.Add(profileHint, 0, 1);
            TableLayoutPanel modes = SessionColumns(34, 33, 33);
            for (int index = 0; index < modeStates.Length; index++)
            {
                modeStates[index] = new AvailabilityIndicator { Dock = DockStyle.Fill, ForeColor = secondaryInk,
                    Font = new Font(Font.FontFamily, 8.5F), Margin = Padding.Empty, TextAlign = ContentAlignment.MiddleLeft };
                modes.Controls.Add(modeStates[index], index, 0);
            }
            content.Controls.Add(modes, 0, 2);
            card.Controls.Add(content);
            return card;
        }

        private void BuildHistorySessionPage()
        {
            Panel page = AddSessionPage("history");
            TableLayoutPanel layout = Rows(0, 53);
            historyTranscriptSlot = new Panel { Dock = DockStyle.Fill, Margin = Padding.Empty };
            layout.Controls.Add(historyTranscriptSlot, 0, 0);
            TableLayoutPanel footer = Columns(0, 168);
            Label privacy = Note("This session only · newest 180 captions · save a file only when you choose.", secondaryInk);
            privacy.Font = new Font(Font.FontFamily, 8.7F);
            footer.Controls.Add(privacy, 0, 0);
            historySaveButton = SessionButton("Save transcript", delegate { SaveTranscriptFile(); }, false);
            historySaveButton.Margin = new Padding(0, 9, 0, 4);
            footer.Controls.Add(historySaveButton, 1, 0);
            layout.Controls.Add(footer, 0, 1);
            page.Controls.Add(layout);
        }

        private void BuildAudioSessionPage()
        {
            Panel page = AddSessionPage("audio");
            TableLayoutPanel content = Rows(76, 340, 160, 86, 55);
            content.Dock = DockStyle.Top;
            content.Height = 717;
            ModernCard modes = LightCard(paper, new Padding(16, 11, 16, 11));
            TableLayoutPanel choices = new TableLayoutPanel { Dock = DockStyle.Fill, Margin = Padding.Empty, ColumnCount = 4, RowCount = 1 };
            choices.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 116));
            for (int i = 0; i < 3; i++) choices.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.333F));
            choices.Controls.Add(Title("Capture mode", paperInk, 10F), 0, 0);
            sessionSystemMode = SessionButton("System audio", delegate { SelectSessionAudioKind("pc"); }, false);
            sessionMicMode = SessionButton("Microphone", delegate { SelectSessionAudioKind("microphone"); }, false);
            sessionBothMode = SessionButton("Both", delegate { SelectSessionAudioKind("both"); }, false);
            choices.Controls.Add(sessionSystemMode, 1, 0);
            choices.Controls.Add(sessionMicMode, 2, 0);
            choices.Controls.Add(sessionBothMode, 3, 0);
            modes.Controls.Add(choices);
            content.Controls.Add(modes, 0, 0);
            TableLayoutPanel columns = SessionColumns(57, 43);
            columns.Padding = new Padding(0, 13, 0, 12);
            ModernCard capture = LightCard(paper, new Padding(18));
            capture.Margin = new Padding(0, 0, 12, 0);
            TableLayoutPanel captureRows = Rows(34, 36, 0, 72, 34);
            sessionAudioSourceTitle = Title("System audio", paperInk, 16F);
            captureRows.Controls.Add(sessionAudioSourceTitle, 0, 0);
            sessionAudioDescription = Note("Choose what reaches the local speech recognizer.", secondaryInk);
            sessionAudioDescription.Font = new Font(Font.FontFamily, 9F);
            captureRows.Controls.Add(sessionAudioDescription, 0, 1);
            captureRows.Controls.Add(BuildAudioControls(), 0, 2);
            Button refresh = SessionButton("Refresh audio sources", delegate { if (connected) Send("devices", null); }, false);
            refresh.Font = new Font(Font.FontFamily, 9F);
            captureRows.Controls.Add(BuildAudioSignalDisplay(), 0, 3);
            captureRows.Controls.Add(refresh, 0, 4);
            capture.Controls.Add(captureRows);
            columns.Controls.Add(capture, 0, 0);
            ModernCard language = LightCard(paper, new Padding(18));
            TableLayoutPanel languages = Rows(38, 57, 57, 0);
            languages.Controls.Add(Title("Translation languages", paperInk, 15F), 0, 0);
            sessionAudioLanguage = SessionButton("Choose source language", delegate { OpenLanguagePicker(); }, false);
            sessionAudioLanguage.Font = new Font(Font.FontFamily, 9.5F);
            languages.Controls.Add(SessionField("Spoken language", sessionAudioLanguage), 0, 1);
            languages.Controls.Add(SessionField("Translate to", SessionFixedTarget()), 0, 2);
            Label target = Note("Incoming translation is English. Recognition settings and language files are available in Settings.", secondaryInk);
            target.Font = new Font(Font.FontFamily, 9F);
            languages.Controls.Add(target, 0, 3);
            language.Controls.Add(languages);
            columns.Controls.Add(language, 1, 0);
            content.Controls.Add(columns, 0, 1);
            content.Controls.Add(BuildAudioRecognitionDisplay(), 0, 2);
            ModernCard tip = LightCard(paper, new Padding(18, 8, 18, 8));
            TableLayoutPanel tipRows = Rows(27, 0);
            tipRows.Controls.Add(Title("Use headphones for clearer listening", paperInk, 12F), 0, 0);
            tipRows.Controls.Add(Note("Keep translated playback out of your microphone. Auto listen opens only the selected input.", secondaryInk), 0, 1);
            tip.Controls.Add(tipRows);
            content.Controls.Add(tip, 0, 3);
            TableLayoutPanel footer = Columns(0, 204);
            footer.Padding = new Padding(0, 10, 0, 0);
            footer.Controls.Add(Note("Device changes apply immediately while listening.", secondaryInk), 0, 0);
            footer.Controls.Add(SessionButton("Return to live session", delegate { ShowSessionPage("live"); }, true), 1, 0);
            content.Controls.Add(footer, 0, 4);
            page.Controls.Add(content);
        }

        private void BuildSettingsSessionPage()
        {
            Panel page = AddSessionPage("settings");
            TableLayoutPanel layout = Rows(90, 150, 150, 150, 90);
            layout.Dock = DockStyle.Top;
            layout.Height = 630;
            ModernCard overview = LightCard(paper, new Padding(18));
            TableLayoutPanel overviewRows = Rows(30, 0);
            overviewRows.Controls.Add(Title("Your local translation workspace", paperInk, 16F), 0, 0);
            sessionSettingsSummary = Note("", secondaryInk);
            sessionSettingsSummary.Font = new Font(Font.FontFamily, 9.5F);
            overviewRows.Controls.Add(sessionSettingsSummary, 0, 1);
            overview.Controls.Add(overviewRows);
            layout.Controls.Add(overview, 0, 0);
            TableLayoutPanel first = SessionColumns(50, 50);
            first.Padding = new Padding(0, 12, 0, 0);
            first.Controls.Add(SessionSettingsCard("Recognition", "Speech models, language codes, phrase timing, CPU threads and screen recognition.",
                "Open recognition settings", delegate { OpenSettingsSection("Audio and screen"); }, true), 0, 0);
            first.Controls.Add(SessionSettingsCard("Language files", "Prepare starter languages, optional models or a local Argos language file.",
                "Manage language files", delegate { OpenSettingsSection("Language files"); }, false), 1, 0);
            layout.Controls.Add(first, 0, 1);
            TableLayoutPanel second = SessionColumns(50, 50);
            second.Padding = new Padding(0, 12, 0, 0);
            second.Controls.Add(SessionSettingsCard("Spoken English", "Choose a local English voice, playback device, speed and volume.",
                "Open voice settings", delegate { OpenSettingsSection("Spoken English"); }, true), 0, 0);
            second.Controls.Add(SessionSettingsCard("App updates", "Version " + CurrentUpdateVersion() + " · signed updates from public GitHub Releases.",
                "Check app updates", delegate { OpenSettingsSection("Updates"); }, false), 1, 0);
            layout.Controls.Add(second, 0, 2);
            TableLayoutPanel third = SessionColumns(50, 50);
            third.Padding = new Padding(0, 12, 0, 0);
            third.Controls.Add(SessionSettingsCard("VR captions", "Native captions inside SteamVR, with placement controls. A single monitor is enough.",
                "Open VR caption settings", delegate { OpenSettingsSection("VR captions"); }, true), 0, 0);
            third.Controls.Add(SessionSettingsCard("Screen reading", "Choose an application or screen area, then preview the capture before watching for text.",
                "Open screen controls", delegate { ShowSessionPage("live"); if (!sessionDetailsOpen) ToggleSessionDetails(); }, false), 1, 0);
            layout.Controls.Add(third, 0, 3);
            Label local = Note("Translation runs locally. Internet access is used for optional downloads and app update checks.\nCaptions stay in this session until you explicitly save a transcript.", secondaryInk);
            local.Padding = new Padding(4, 12, 4, 0);
            local.Font = new Font(Font.FontFamily, 9F);
            layout.Controls.Add(local, 0, 4);
            page.Controls.Add(layout);
        }

        private Control SessionSettingsCard(string title, string description, string action, EventHandler click, bool left)
        {
            ModernCard card = LightCard(paper, new Padding(16, 9, 16, 10));
            card.Margin = new Padding(0, 0, left ? 12 : 0, 0);
            TableLayoutPanel rows = Rows(28, 0, 32);
            rows.Controls.Add(Title(title, paperInk, 13F), 0, 0);
            Label detail = Note(description, secondaryInk);
            detail.Font = new Font(Font.FontFamily, 9F);
            rows.Controls.Add(detail, 0, 1);
            rows.Controls.Add(SessionButton(action, click, false), 0, 2);
            card.Controls.Add(rows);
            return card;
        }

        private TableLayoutPanel SessionColumns(params float[] percentages)
        {
            TableLayoutPanel row = new TableLayoutPanel { Dock = DockStyle.Fill, Margin = Padding.Empty,
                RowCount = 1, ColumnCount = percentages.Length, BackColor = Color.Transparent };
            foreach (float value in percentages) row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, value));
            row.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            return row;
        }

        private Control SessionField(string label, Control value)
        {
            TableLayoutPanel fieldPanel = Rows(21, 0);
            fieldPanel.Padding = new Padding(0, 0, 9, 0);
            Label title = Note(label, secondaryInk);
            title.Font = new Font(Font.FontFamily, 9F);
            fieldPanel.Controls.Add(title, 0, 0);
            value.Dock = DockStyle.Fill;
            fieldPanel.Controls.Add(value, 0, 1);
            return fieldPanel;
        }

        private Control SessionFixedTarget()
        {
            Label target = Note("English", paperInk);
            target.BackColor = field;
            target.Padding = new Padding(10, 0, 0, 0);
            target.AccessibleName = "Translation target: English, read only";
            target.AccessibleDescription = "Incoming translation currently supports English output.";
            target.AccessibleRole = AccessibleRole.StaticText;
            return target;
        }

        private Button SessionButton(string text, EventHandler click, bool primary)
        {
            Button button = MakeButton(text, click, primary);
            button.Font = new Font(Font.FontFamily, 9.5F, primary ? FontStyle.Bold : FontStyle.Regular);
            button.Dock = DockStyle.Fill;
            button.Margin = new Padding(0, 0, 7, 0);
            button.BackColor = primary ? accent : field;
            button.ForeColor = primary ? background : paperInk;
            button.FlatAppearance.BorderColor = primary ? accent : border;
            return button;
        }

        private float SessionScale() { return sessionBrand == null ? 1F : Math.Max(.75F, sessionBrand.Width / 27F); }
        private void LayoutSessionPage()
        {
            if (sessionLiveLayout == null || !sessionPages.ContainsKey("live")) return;
            float scale = SessionScale();
            sessionLiveLayout.RowStyles[1].SizeType = SizeType.Absolute;
            sessionLiveLayout.RowStyles[1].Height = sessionDetailsOpen ? 108 * scale : 0;
            sessionLiveLayout.RowStyles[2].SizeType = SizeType.Percent;
            sessionLiveLayout.RowStyles[2].Height = 100;
            sessionLiveLayout.Height = Math.Max((int)((sessionDetailsOpen ? 716 : 608) * scale), sessionPages["live"].ClientSize.Height);
        }

        private void ToggleSessionDetails()
        {
            sessionDetailsOpen = !sessionDetailsOpen;
            sessionCaptureDetails.Visible = sessionDetailsOpen;
            sessionDetailsButton.Text = sessionDetailsOpen ? "Hide screen & language options" : "Screen & language options";
            LayoutSessionPage();
        }

        internal void ShowSessionPage(string page)
        {
            Panel target;
            if (String.IsNullOrEmpty(page) || !sessionPages.TryGetValue(page, out target)) return;
            bool restore = output != null && output.IsHandleCreated;
            TranscriptPosition position = restore ? new TranscriptPosition(output) : default(TranscriptPosition);
            if ((page == "live" || page == "history") && sessionTranscriptCard != null)
            {
                Panel slot = page == "live" ? liveTranscriptSlot : historyTranscriptSlot;
                if (sessionTranscriptCard.Parent != slot) slot.Controls.Add(sessionTranscriptCard);
            }
            foreach (var entry in sessionPages) entry.Value.Visible = String.Equals(entry.Key, page, StringComparison.OrdinalIgnoreCase);
            target.BringToFront();
            activeSessionPage = page;
            foreach (var entry in sessionNavigation)
            {
                entry.Value.SelectedPage = String.Equals(entry.Key, page, StringComparison.OrdinalIgnoreCase);
                entry.Value.AccessibleDescription = entry.Value.SelectedPage ? "Selected page" : "Open " + entry.Value.Text.ToLowerInvariant();
                entry.Value.Invalidate();
            }
            sessionPageTitle.Text = page == "history" ? "Session history" : page == "audio" ? "Audio setup" : page == "settings" ? "Settings" : "Live translation";
            sessionPageDescription.Text = page == "history" ? "Review the captions from this session." : page == "audio" ?
                "Choose what to listen to and check your audio." : page == "settings" ? "Make LiveTranslate work for your setup." : "Follow the conversation as it happens.";
            if (sessionTranscriptTitle != null) sessionTranscriptTitle.Text = page == "history" ? "Session captions" : "Translation";
            LayoutSessionPage();
            target.PerformLayout();
            if (restore && (page == "live" || page == "history")) position.Restore(output, 0);
            RefreshSessionUi();
        }

        private void OpenSettingsSection(string text)
        {
            if (settingsTabs != null)
                foreach (TabPage page in settingsTabs.TabPages)
                    if (String.Equals(page.Text, text, StringComparison.OrdinalIgnoreCase)) { settingsTabs.SelectedTab = page; break; }
            OpenSettings();
        }

        private void SelectSessionAudioKind(string kind)
        {
            if (devices == null || !devices.Enabled) return;
            Choice current = devices.SelectedItem as Choice;
            if (current != null && current.Code == kind) { RefreshSessionUi(); return; }
            for (int index = 0; index < devices.Items.Count; index++)
            {
                Choice choice = devices.Items[index] as Choice;
                if (choice != null && choice.Code == kind) { devices.SelectedIndex = index; RefreshSessionUi(); return; }
            }
            SetStatus("That audio source is unavailable. Refresh audio sources or connect a device.");
        }

        internal void ToggleSessionPause()
        {
            if (closing || SetupRunning() || profileBusy) return;
            if (!SessionCanPause) { ShowSessionPage("audio"); SetStatus("Choose an input and turn on Auto listen or Watch screen."); return; }
            changingSessionState = true;
            try
            {
                if (!sessionPaused)
                {
                    resumeSessionAudio = audioWanted;
                    resumeSessionScreen = screenArmed || screenWanted;
                    sessionPaused = true;
                    screenArmed = false;
                    SetSwitch(screenToggle, false);
                    StopAudio(); StopScreen(); CancelReadOnce();
                    SetStatus("Translation paused. Existing captions remain in session history.");
                }
                else
                {
                    bool audio = resumeSessionAudio, screen = resumeSessionScreen;
                    sessionPaused = false;
                    resumeSessionAudio = resumeSessionScreen = false;
                    screenArmed = screen;
                    SetSwitch(screenToggle, screen);
                    if (screen) TryStartScreen();
                    if (audio) { audioWanted = true; SetSwitch(audioToggle, true); RestartAudio(); }
                    if (audio && !audioWanted)
                        SetStatus("Audio could not resume. " + audioStateLabel.Text);
                    else if (screen && !screenWanted)
                        SetStatus(screenStateLabel.Text);
                    else if (!audio && !screen)
                        SetStatus("The paused screen read was canceled. Use Read once to scan again.");
                    else
                        SetStatus("Session resumed.");
                }
            }
            finally { changingSessionState = false; UpdateControls(); RefreshSessionUi(); }
        }

        internal void EndSession()
        {
            if (closing) return;
            changingSessionState = true;
            try
            {
                sessionPaused = resumeSessionAudio = resumeSessionScreen = false;
                screenArmed = false;
                SetSwitch(screenToggle, false);
                StopAudio(); StopScreen(); CancelReadOnce(); ClearOverlayChannel("");
                SetStatus("Session ended. Captions remain in session history until you clear or close the app.");
            }
            finally { changingSessionState = false; UpdateControls(); RefreshSessionUi(); }
        }

        private void SaveTranscriptFile()
        {
            if (history.Count == 0) { SetStatus("There are no session captions to save yet."); return; }
            using (SaveFileDialog dialog = new SaveFileDialog { Title = "Save this session transcript", Filter = "Text transcript (*.txt)|*.txt",
                DefaultExt = "txt", AddExtension = true, OverwritePrompt = true,
                FileName = "LiveTranslate-session-" + DateTime.Now.ToString("yyyy-MM-dd-HHmm") + ".txt" })
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                try { File.WriteAllText(dialog.FileName, output.Text, new UTF8Encoding(false)); SetStatus("Transcript saved to " + dialog.FileName); }
                catch (Exception error) { SetStatus("The transcript could not be saved. " + error.Message); }
            }
        }

        private void RefreshAudioMode(Button button, string kind, string selected)
        {
            if (button == null || devices == null) return;
            bool available = false;
            foreach (object item in devices.Items) { Choice choice = item as Choice; if (choice != null && choice.Code == kind) available = true; }
            button.Enabled = devices.Enabled && available;
            button.BackColor = selected == kind ? accent : field;
            button.ForeColor = selected == kind ? background : paperInk;
            button.FlatAppearance.BorderColor = selected == kind ? accent : border;
        }

        internal void RefreshSessionUi()
        {
            if (sessionStatePill == null || IsDisposed) return;
            RefreshAudioDiagnosticControls();
            if (!changingSessionState && sessionPaused && (audioWanted || screenArmed || screenWanted))
                sessionPaused = resumeSessionAudio = resumeSessionScreen = false;
            sessionStatePill.Text = SessionStatusText;
            sessionStatePill.ForeColor = sessionPaused ? secondaryInk : audioWanted || screenWanted ? accent : secondaryInk;
            if (sessionPauseButton != null) { sessionPauseButton.Text = SessionPauseLabel; sessionPauseButton.Enabled = SessionCanPause; }
            if (sessionEndButton != null) sessionEndButton.Enabled = sessionPaused || audioWanted || screenArmed || screenWanted || oneShotPending;
            if (sessionSaveButton != null) sessionSaveButton.Enabled = history.Count > 0;
            if (historySaveButton != null) historySaveButton.Enabled = history.Count > 0;
            Choice device = devices == null ? null : devices.SelectedItem as Choice;
            if (sessionAudioSummary != null) sessionAudioSummary.Text = device == null ? "Choose audio source" : device.Name;
            if (sessionAudioLanguage != null && profileSelector != null)
            {
                sessionAudioLanguage.Text = ProfileName(ProfileCode());
                sessionAudioLanguage.Enabled = pickLanguage == null || pickLanguage.Enabled;
            }
            string kind = device == null ? "" : device.Code;
            RefreshAudioMode(sessionSystemMode, "pc", kind);
            RefreshAudioMode(sessionMicMode, "microphone", kind);
            RefreshAudioMode(sessionBothMode, "both", kind);
            if (sessionAudioSourceTitle != null) sessionAudioSourceTitle.Text = kind == "microphone" ? "Microphone" : kind == "both" ? "Computer + microphone" : "System audio";
            if (sessionAudioDescription != null) sessionAudioDescription.Text = kind == "microphone" ? "Translate the selected microphone input." :
                kind == "both" ? "Translate playback and microphone inputs." : "Translate the sound playing on this computer.";
            if (sessionSettingsSummary != null) sessionSettingsSummary.Text = "LiveTranslate " + CurrentUpdateVersion() + " · " +
                (connected ? "local engine connected" : "local engine not connected") + " · incoming translation to English";
        }
    }
}
