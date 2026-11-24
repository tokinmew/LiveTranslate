using System;
using System.Drawing;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed partial class MainForm
    {
        private Button copyTranscript, clearTranscript, pickLanguage, translateButton;
        private Label audioDeviceHint;
        private TableLayoutPanel screenRegionRow;
        private readonly Label[] modeStates = new Label[3];
        private Label transcriptCount;
        private readonly ToolTip dashboardTips = new ToolTip { AutoPopDelay = 9000, InitialDelay = 480, ReshowDelay = 150 };

        private static void FitToDisplay(Form window)
        {
            Rectangle available = Screen.FromControl(window).WorkingArea;
            window.MinimumSize = new Size(Math.Min(window.MinimumSize.Width, available.Width), Math.Min(window.MinimumSize.Height, available.Height));
            Size size = new Size(Math.Min(window.Width, available.Width), Math.Min(window.Height, available.Height));
            int x = Math.Max(available.Left, Math.Min(window.Left, available.Right - size.Width));
            int y = Math.Max(available.Top, Math.Min(window.Top, available.Bottom - size.Height));
            window.Bounds = new Rectangle(new Point(x, y), size);
        }

        private void BuildUi()
        {
            BuildSessionWorkspace();
            customTextSource.SelectedIndexChanged += delegate { UpdateTranslateAction(); };
            Disposed += delegate { dashboardTips.Dispose(); if (writtenLanguageSetup != null) writtenLanguageSetup.Dispose(); };
            UpdateTranscriptTools();
            RefreshSessionUi();
        }

        private ModernCard BuildCapturePanel()
        {
            ModernCard card = LightCard(paper, new Padding(16, 10, 16, 8));
            TableLayoutPanel content = Rows(55, 0);
            TableLayoutPanel fields = SessionColumns(34, 35, 31);
            profileSelector = Combo();
            profileSelector.Visible = false;
            profileSelector.TabStop = false;
            AddPriorityChoices(profileSelector, true);
            profileSelector.SelectedIndex = 0;
            profileSelector.SelectedIndexChanged += delegate { SyncLanguageButton(); ProfileChanged(); RefreshSessionUi(); };
            card.Controls.Add(profileSelector);
            sessionAudioSummary = SessionButton("Choose audio source", delegate { ShowSessionPage("audio"); }, false);
            sessionAudioSummary.AccessibleName = "Audio source: open audio setup";
            fields.Controls.Add(SessionField("Audio source", sessionAudioSummary), 0, 0);
            pickLanguage = MakeButton("Choose source language", delegate { OpenLanguagePicker(); }, false);
            ((ModernButton)pickLanguage).IsPicker = true;
            pickLanguage.AccessibleName = "Choose source language";
            pickLanguage.Font = new Font(Font.FontFamily, 10F);
            pickLanguage.Margin = new Padding(0, 0, 12, 0);
            pickLanguage.Dock = DockStyle.Fill;
            fields.Controls.Add(SessionField("Spoken / source language", pickLanguage), 1, 0);
            fields.Controls.Add(SessionField("Translate to", SessionFixedTarget()), 2, 0);
            SyncLanguageButton();
            content.Controls.Add(fields, 0, 0);
            content.Controls.Add(BuildScreenControls(), 0, 1);
            card.Controls.Add(content);
            return card;
        }

        private Control BuildScreenControls()
        {
            TableLayoutPanel panel = Rows(34, 23);
            TableLayoutPanel row = new TableLayoutPanel { Dock = DockStyle.Fill, Margin = Padding.Empty, ColumnCount = 4, RowCount = 1 };
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 162));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 112));
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 100));
            row.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            screenToggle = Switch("Watch screen", ScreenToggleChanged);
            TableLayoutPanel watching = Columns(0, 45);
            watching.Padding = new Padding(0, 0, 10, 0);
            watching.Controls.Add(Note("Watch screen", paperInk), 0, 0);
            watching.Controls.Add(screenToggle, 1, 0);
            row.Controls.Add(watching, 0, 0);
            screenRegionRow = Columns(0, 85);
            regionLabel = Note("Primary display", secondaryInk);
            regionLabel.Font = new Font(Font.FontFamily, 9F);
            screenRegionRow.Controls.Add(regionLabel, 0, 0);
            japaneseDirection = Combo();
            japaneseDirection.AccessibleName = "Japanese text direction";
            japaneseDirection.Font = new Font(Font.FontFamily, 8.5F);
            japaneseDirection.Items.Add(new Choice("horizontal", "Horizontal"));
            japaneseDirection.Items.Add(new Choice("vertical", "Vertical"));
            japaneseDirection.SelectedIndex = 0;
            japaneseDirection.SelectedIndexChanged += delegate {
                if (!applyingProfile && ProfileCode() == "ja") { ApplyProfile(false); CancelReadOnce(); ReconfigureScreen(); }
            };
            screenRegionRow.Controls.Add(japaneseDirection, 1, 0);
            row.Controls.Add(screenRegionRow, 1, 0);
            selectArea = SessionButton("Capture area", ChooseTarget, false);
            readOnce = SessionButton("Read once", ReadScreenOnce, false);
            selectArea.Margin = new Padding(6, 1, 5, 1);
            readOnce.Margin = new Padding(0, 1, 0, 1);
            row.Controls.Add(selectArea, 2, 0);
            row.Controls.Add(readOnce, 3, 0);
            panel.Controls.Add(row, 0, 0);
            TableLayoutPanel hint = Columns(0, 174);
            screenStateLabel = Note("Waiting for local language files.", secondaryInk);
            screenStateLabel.Font = new Font(Font.FontFamily, 8.7F);
            screenStateLabel.TextChanged += delegate { dashboardTips.SetToolTip(screenStateLabel, screenStateLabel.Text); };
            hint.Controls.Add(screenStateLabel, 0, 0);
            sessionDetailsButton = SessionButton("Screen & language options", delegate { ToggleSessionDetails(); }, false);
            sessionDetailsButton.Font = new Font(Font.FontFamily, 8F);
            sessionDetailsButton.Margin = Padding.Empty;
            hint.Controls.Add(sessionDetailsButton, 1, 0);
            panel.Controls.Add(hint, 0, 1);
            return panel;
        }

        private Control BuildAudioControls()
        {
            TableLayoutPanel panel = Rows(37, 33, 0);
            panel.Padding = new Padding(0, 6, 0, 3);
            audioToggle = Switch("Listen to computer audio or microphone", AudioToggleChanged);
            panel.Controls.Add(CaptureHeading("Auto listen", DashboardGlyph.Kind.Audio, audioToggle), 0, 0);
            devices = Combo();
            devices.AccessibleName = "Audio device";
            devices.DropDownWidth = 460;
            dashboardTips.SetToolTip(devices, "Select computer playback, a microphone, or both when available.");
            devices.SelectedIndexChanged += delegate {
                if (updatingDevices) return;
                if (audioWanted) RestartAudio();
                RefreshSessionUi();
            };
            Panel source = new Panel { Dock = DockStyle.Fill, Margin = new Padding(0, 1, 0, 2), BackColor = Color.Transparent };
            source.Controls.Add(devices);
            audioDeviceHint = Note("Waiting for audio devices", muted);
            audioDeviceHint.Padding = new Padding(9, 0, 0, 0);
            audioDeviceHint.BackColor = field;
            audioDeviceHint.Font = new Font(Font.FontFamily, 9F);
            source.Controls.Add(audioDeviceHint);
            audioDeviceHint.BringToFront();
            panel.Controls.Add(source, 0, 1);
            audioStateLabel = Note("Off. Choose a source and turn on Auto listen.", muted);
            audioStateLabel.TextAlign = ContentAlignment.MiddleLeft;
            audioStateLabel.Font = new Font(Font.FontFamily, 9F);
            audioStateLabel.TextChanged += delegate { dashboardTips.SetToolTip(audioStateLabel, audioStateLabel.Text); };
            panel.Controls.Add(audioStateLabel, 0, 2);
            return panel;
        }

        private ModernCard BuildTranscript()
        {
            ModernCard card = LightCard(paper, new Padding(18, 9, 18, 12));
            TableLayoutPanel form = Rows(44, 38, 1, 0);
            TableLayoutPanel heading = Columns(0, 145);
            sessionTranscriptTitle = Title("Translation", paperInk, 15F);
            heading.Controls.Add(sessionTranscriptTitle, 0, 0);
            overlayToggle = new CaptionOption { Text = "Caption overlay", AccessibleName = "Show live caption overlay", AutoSize = false,
                Checked = true, ForeColor = paperInk, BackColor = paper, Anchor = AnchorStyles.Right, Size = new Size(142,32), Margin = Padding.Empty };
            overlayToggle.CheckedChanged += delegate { OverlayPreferenceChanged(); };
            dashboardTips.SetToolTip(overlayToggle, "Show translated screen text near its source and speech captions over other windows.");
            heading.Controls.Add(overlayToggle, 1, 0);
            form.Controls.Add(heading, 0, 0);
            TableLayoutPanel bar = Columns(0, 136);
            TableLayoutPanel options = Columns(132, 0);
            showSource = new CaptionOption { Text = "Both languages", AccessibleName = "Show source text in the transcript", Checked = true,
                AutoSize = false, Size = new Size(126,28), Anchor = AnchorStyles.Left, BackColor = paper, ForeColor = secondaryInk, Margin = Padding.Empty, Font = new Font(Font.FontFamily, 9.5F) };
            showSource.CheckedChanged += delegate { RenderCaptions(); };
            options.Controls.Add(showSource, 0, 0);
            transcriptCount = Note("", secondaryInk);
            transcriptCount.Margin = Padding.Empty;
            transcriptCount.Font = new Font(Font.FontFamily, 9F);
            options.Controls.Add(transcriptCount, 1, 0);
            bar.Controls.Add(options, 0, 0);
            TableLayoutPanel actions = Columns(72, 0);
            copyTranscript = LightButton("Copy", delegate
            {
                try
                {
                    if (output.TextLength == 0) return;
                    Clipboard.SetText(output.Text);
                    SetStatus("Captions copied.");
                }
                catch (Exception ex) { SetStatus(ex.Message); }
            });
            clearTranscript = LightButton("Clear", delegate { history.Clear(); RenderCaptions(); ClearOverlayChannel(""); });
            DockAction(copyTranscript, new Padding(0, 1, 6, 6));
            DockAction(clearTranscript, new Padding(0, 1, 0, 6));
            actions.Controls.Add(copyTranscript, 0, 0);
            actions.Controls.Add(clearTranscript, 1, 0);
            bar.Controls.Add(actions, 1, 0);
            form.Controls.Add(bar, 0, 1);
            form.Controls.Add(Divider(border), 0, 2);
            Panel body = new Panel { Dock = DockStyle.Fill, BackColor = paper, Margin = new Padding(0, 10, 0, 0) };
            output = new RichTextBox { AccessibleName = "English caption transcript", Dock = DockStyle.Fill, ReadOnly = true, BackColor = paper,
                ForeColor = paperInk, Font = captionFont, BorderStyle = BorderStyle.None, DetectUrls = false, HideSelection = false, WordWrap = true };
            emptyOutput = new EmptyTranscript(SetupSelected) { Dock = DockStyle.Fill, ForeColor = paperInk, BackColor = paper, AccessibleRole = AccessibleRole.StaticText,
                Text = "Ready for your first caption" };
            body.Controls.Add(output);
            body.Controls.Add(emptyOutput);
            emptyOutput.BringToFront();
            form.Controls.Add(body, 0, 3);
            card.Controls.Add(form);
            return card;
        }

        private ModernCard BuildComposer()
        {
            ModernCard card = LightCard(paper, new Padding(16, 9, 16, 10));
            card.Margin = new Padding(0, 10, 0, 0);
            TableLayoutPanel form = Rows(31, 0, 37);
            TableLayoutPanel heading = Columns(0, 198);
            heading.Controls.Add(Title("Translate text", paperInk, 13F), 0, 0);
            TableLayoutPanel textActions = Columns(126, 0);
            Button practice = LightButton("Practice a reply", delegate { OpenReplyPractice(); });
            practice.AccessibleDescription = "Translate your English reply and read its pronunciation.";
            DockAction(practice, new Padding(0, 0, 8, 3));
            textActions.Controls.Add(practice, 0, 0);
            Button paste = LightButton("Paste", delegate
            {
                try { if (Clipboard.ContainsText()) input.Text = Clipboard.GetText(); }
                catch (Exception ex) { SetStatus(ex.Message); }
            });
            DockAction(paste, new Padding(0, 0, 0, 3));
            textActions.Controls.Add(paste, 1, 0);
            heading.Controls.Add(textActions, 1, 0);
            form.Controls.Add(heading, 0, 0);
            input = new ComposerEntry { Dock = DockStyle.Fill, BorderStyle = BorderStyle.None };
            input.AccessibleName = "Text to translate";
            input.Multiline = true;
            input.AcceptsReturn = true;
            input.ScrollBars = ScrollBars.None;
            input.Font = new Font(Font.FontFamily, 11F);
            input.BackColor = field;
            input.ForeColor = paperInk;
            input.Margin = Padding.Empty;
            Panel editor = new Panel { Dock = DockStyle.Fill, BackColor = input.BackColor, Padding = new Padding(9, 6, 5, 4), Margin = new Padding(0, 3, 0, 5) };
            editor.Paint += delegate(object sender, PaintEventArgs paint) { ControlPaint.DrawBorder(paint.Graphics, editor.ClientRectangle, input.Focused ? accent : border, ButtonBorderStyle.Solid); };
            input.Enter += delegate { editor.Invalidate(); };
            input.Leave += delegate { editor.Invalidate(); };
            input.TextChanged += delegate { UpdateTranslateAction(); };
            input.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyData == (Keys.Control | Keys.Enter)) { e.SuppressKeyPress = true; TranslateInput(); }
            };
            editor.Controls.Add(input);
            form.Controls.Add(editor, 0, 1);
            TableLayoutPanel footer = Columns(0, 185);
            Button example = LightButton("Try example", delegate { InsertExample(); });
            example.Width = 107;
            example.Anchor = AnchorStyles.Left;
            example.Margin = Padding.Empty;
            footer.Controls.Add(example, 0, 0);
            Button translate = translateButton = MakeButton("Translate to English", delegate { TranslateInput(); }, true);
            ((ModernButton)translate).Symbol = ButtonSymbol.Arrow;
            translate.BackColor = accent;
            translate.ForeColor = background;
            translate.FlatAppearance.BorderColor = accent;
            DockAction(translate, new Padding(0, 2, 0, 1));
            dashboardTips.SetToolTip(translate, "Translate typed text (Ctrl+Enter)");
            footer.Controls.Add(translate, 1, 0);
            form.Controls.Add(footer, 0, 2);
            card.Controls.Add(form);
            return card;
        }

        private void TranslateInput()
        {
            if (String.IsNullOrWhiteSpace(input.Text)) { SetStatus("Type or paste text first."); input.Focus(); return; }
            if (!connected || SetupRunning() || profileBusy) { SetStatus("Wait for the local engine before translating text."); return; }
            string source = TextSource(), text = input.Text.Trim();
            if (IsTypedRequestPending(text, source)) return;
            if (Send("translate", Dict("text", text, "source", source))) UpdateTranslateAction();
        }

        private bool IsTypedRequestPending(string text, string source)
        {
            foreach (PendingRequest request in pending.Values)
                if (request.TypedText == text && request.TypedSource == source) return true;
            return false;
        }

        private void UpdateTranslateAction()
        {
            if (translateButton == null) return;
            bool inFlight = !String.IsNullOrWhiteSpace(input.Text) && IsTypedRequestPending(input.Text.Trim(), TextSource());
            translateButton.Text = inFlight ? "Translating…" : "Translate to English";
            translateButton.Enabled = connected && !profileBusy && !SetupRunning() && !inFlight && !String.IsNullOrWhiteSpace(input.Text);
        }

        private void UpdateTranscriptTools()
        {
            if (copyTranscript == null || clearTranscript == null || transcriptCount == null) return;
            copyTranscript.Enabled = clearTranscript.Enabled = history.Count > 0;
            transcriptCount.Text = history.Count == 0 ? "" : history.Count == 1 ? "1 caption" : history.Count + " captions";
            RefreshSessionUi();
        }

        private Control CaptureHeading(string text, DashboardGlyph.Kind kind, ModernSwitch toggle)
        {
            TableLayoutPanel row = Columns(0, 43);
            TableLayoutPanel left = Columns(29, 0);
            left.Controls.Add(new DashboardGlyph(kind) { Size = new Size(22, 22), Anchor = AnchorStyles.Left, Margin = Padding.Empty }, 0, 0);
            left.Controls.Add(Title(text, ink, 12F), 1, 0);
            row.Controls.Add(left, 0, 0);
            row.Controls.Add(toggle, 1, 0);
            return row;
        }

        private ModernSwitch Switch(string name, EventHandler handler)
        {
            ModernSwitch toggle = new ModernSwitch { AccessibleName = name, AccentColor = accent,
                Size = new Size(42, 23), Margin = Padding.Empty, Anchor = AnchorStyles.Right };
            toggle.CheckedChanged += handler;
            return toggle;
        }

        private static void DockAction(Button button, Padding margin) { button.Dock = DockStyle.Fill; button.Margin = margin; }
        private static Panel Divider(Color color) { return new Panel { BackColor = color, Dock = DockStyle.Fill, Margin = Padding.Empty }; }

        private Label Title(string text, Color color, float size)
        {
            Label label = Note(text, color);
            label.TextAlign = ContentAlignment.MiddleLeft;
            label.Font = new Font(Font.FontFamily, size, FontStyle.Bold);
            return label;
        }

        private ModernCard LightCard(Color fill, Padding inset)
        {
            ModernCard card = Card(fill);
            card.BorderColor = border;
            card.Padding = inset;
            return card;
        }
    }
}
