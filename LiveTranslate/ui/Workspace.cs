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
            TableLayoutPanel main = Rows(70, 0, 31);
            main.Padding = new Padding(19, 2, 19, 3);
            main.BackColor = background;
            Controls.Add(main);
            TableLayoutPanel header = Columns(0, 415);
            TableLayoutPanel brand = Columns(50, 0);
            DashboardGlyph brandMark = new DashboardGlyph(DashboardGlyph.Kind.Brand) { Size = new Size(38, 38), Anchor = AnchorStyles.Left, Margin = Padding.Empty };
            brand.Controls.Add(brandMark, 0, 0);
            brand.Controls.Add(Title("Live Translate", paperInk, 18), 1, 0);
            header.Controls.Add(brand, 0, 0);
            TableLayoutPanel tools = Columns(0, 224);
            engineBadge = new EngineIndicator { Text = "Checking local engine", Dock = DockStyle.Fill, Margin = new Padding(0,0,12,0), ForeColor = paperInk, Font = new Font(Font.FontFamily, 9F) };
            tools.Controls.Add(engineBadge, 0, 0);
            TableLayoutPanel buttons = Columns(118, 0);
            Button vr = LightButton("VR captions", delegate { OpenVrCaptions(); });
            Button settings = LightButton("Settings", delegate { OpenSettings(); });
            ((ModernButton)vr).Symbol = ButtonSymbol.Headset;
            ((ModernButton)settings).Symbol = ButtonSymbol.Settings;
            vr.Size = new Size(112, 35);
            settings.Size = new Size(100, 35);
            vr.Margin = settings.Margin = Padding.Empty;
            vr.Anchor = AnchorStyles.Left;
            settings.Anchor = AnchorStyles.Right;
            vr.AccessibleDescription = "Open a caption window for your headset's PC desktop view.";
            dashboardTips.SetToolTip(vr, vr.AccessibleDescription);
            buttons.Controls.Add(vr, 0, 0);
            buttons.Controls.Add(settings, 1, 0);
            tools.Controls.Add(buttons, 1, 0);
            header.Controls.Add(tools, 1, 0);
            main.Controls.Add(header, 0, 0);

            TableLayoutPanel workspace = Columns(322, 0);
            workspace.TabIndex = 0;
            header.TabIndex = 1;
            workspace.Controls.Add(BuildCapturePanel(), 0, 0);
            TableLayoutPanel right = Rows(0, 166);
            right.Controls.Add(BuildTranscript(), 0, 0);
            right.Controls.Add(BuildComposer(), 0, 1);
            workspace.Controls.Add(right, 1, 0);
            main.Controls.Add(workspace, 0, 1);
            status = Note("Checking local language files…", secondaryInk);
            status.TextAlign = ContentAlignment.MiddleLeft;
            status.AccessibleRole = AccessibleRole.StatusBar;
            main.Controls.Add(status, 0, 2);
            // Reflow fixed columns in logical pixels after Windows scales the form.
            EventHandler adapt = delegate {
                if (!main.IsHandleCreated) return;
                float dpi = brandMark.Width / 38F;
                bool compact = main.ClientSize.Width < 920 * dpi;
                workspace.ColumnStyles[0].Width = (int)Math.Round((compact ? 280 : 322) * dpi);
                right.RowStyles[1].Height = (int)Math.Round((main.ClientSize.Height < 600 * dpi ? 145 : 166) * dpi);
            };
            main.HandleCreated += adapt;
            main.SizeChanged += adapt;
            customTextSource.SelectedIndexChanged += delegate { UpdateTranslateAction(); };
            Disposed += delegate { dashboardTips.Dispose(); if (writtenLanguageSetup != null) writtenLanguageSetup.Dispose(); };
            UpdateTranscriptTools();
        }

        private ModernCard BuildCapturePanel()
        {
            ModernCard rail = Card(surface);
            rail.BorderColor = surface;
            rail.Padding = new Padding(17, 14, 17, 14);
            rail.Margin = new Padding(0, 0, 14, 0);
            TableLayoutPanel form = Rows(36, 27, 39, 43, 1, 151, 1, 124, 1, 0, 55, 36);
            form.Controls.Add(Title("Capture sources", ink, 16F), 0, 0);
            TableLayoutPanel route = Columns(0, 109);
            route.Controls.Add(Title("Translate from", muted, 9.5F), 0, 0);
            Label target = Kicker("\u2192  ENGLISH");
            target.TextAlign = ContentAlignment.MiddleRight;
            target.ForeColor = accent;
            route.Controls.Add(target, 1, 0);
            form.Controls.Add(route, 0, 1);
            profileSelector = Combo();
            profileSelector.Visible = false;
            profileSelector.TabStop = false;
            AddPriorityChoices(profileSelector, true);
            profileSelector.SelectedIndex = 0;
            profileSelector.SelectedIndexChanged += delegate { SyncLanguageButton(); ProfileChanged(); };
            rail.Controls.Add(profileSelector);
            pickLanguage = MakeButton("Choose source language", delegate { OpenLanguagePicker(); }, false);
            ((ModernButton)pickLanguage).IsPicker = true;
            pickLanguage.AccessibleName = "Choose source language";
            pickLanguage.Font = new Font(Font.FontFamily, 10.2F, FontStyle.Bold);
            DockAction(pickLanguage, new Padding(0, 1, 0, 1));
            dashboardTips.SetToolTip(pickLanguage, "Search by language name or code and check available inputs.");
            form.Controls.Add(pickLanguage, 0, 2);
            SyncLanguageButton();
            profileHint = Note("", muted);
            profileHint.Font = new Font(Font.FontFamily, 9F);
            form.Controls.Add(profileHint, 0, 3);
            form.Controls.Add(Divider(border), 0, 4);
            form.Controls.Add(BuildScreenControls(), 0, 5);
            form.Controls.Add(Divider(border), 0, 6);
            form.Controls.Add(BuildAudioControls(), 0, 7);
            form.Controls.Add(Divider(border), 0, 8);
            TableLayoutPanel readiness = Rows(24, 0);
            profileReadiness = Title("Language files", muted, 9F);
            readiness.Controls.Add(profileReadiness, 0, 0);
            TableLayoutPanel modes = new TableLayoutPanel { Dock = DockStyle.Fill, Margin = Padding.Empty, RowCount = 1, ColumnCount = 3, BackColor = Color.Transparent };
            for (int index = 0; index < modeStates.Length; index++)
            {
                modes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F / 3));
                modeStates[index] = new AvailabilityIndicator { Dock = DockStyle.Fill, ForeColor = muted, Margin = Padding.Empty };
                modeStates[index].TextAlign = ContentAlignment.MiddleLeft;
                modeStates[index].Font = new Font(Font.FontFamily, 8.6F);
                modes.Controls.Add(modeStates[index], index, 0);
            }
            readiness.Controls.Add(modes, 0, 1);
            form.Controls.Add(readiness, 0, 10);
            setupProfile = MakeButton("Manage language files", SetupSelected, false);
            DockAction(setupProfile, new Padding(0, 2, 0, 0));
            form.Controls.Add(setupProfile, 0, 11);
            Panel scroll = new Panel { Dock = DockStyle.Fill, AutoScroll = true, BackColor = Color.Transparent, Margin = Padding.Empty };
            form.Dock = DockStyle.Top;
            int minHeight = 0;
            foreach (RowStyle row in form.RowStyles) if (row.SizeType == SizeType.Absolute) minHeight += (int)Math.Ceiling(row.Height);
            form.MinimumSize = new Size(0, minHeight);
            scroll.SizeChanged += delegate { form.Height = Math.Max(form.MinimumSize.Height, scroll.ClientSize.Height); };
            scroll.Controls.Add(form);
            rail.Controls.Add(scroll);
            return rail;
        }

        private Control BuildScreenControls()
        {
            TableLayoutPanel panel = Rows(37, 28, 34, 0);
            panel.Padding = new Padding(0, 6, 0, 4);
            screenToggle = Switch("Watch screen", ScreenToggleChanged);
            panel.Controls.Add(CaptureHeading("Watch screen", DashboardGlyph.Kind.Screen, screenToggle), 0, 0);
            TableLayoutPanel region = screenRegionRow = Columns(0, 136);
            regionLabel = Note("Primary display", muted);
            regionLabel.Font = new Font(Font.FontFamily, 9F);
            region.Controls.Add(regionLabel, 0, 0);
            japaneseDirection = Combo();
            japaneseDirection.AccessibleName = "Japanese text direction";
            japaneseDirection.Font = new Font(Font.FontFamily, 8.8F);
            japaneseDirection.Items.Add(new Choice("horizontal", "Horizontal"));
            japaneseDirection.Items.Add(new Choice("vertical", "Vertical"));
            dashboardTips.SetToolTip(japaneseDirection, "Direction of the Japanese text on screen.");
            japaneseDirection.SelectedIndex = 0;
            japaneseDirection.SelectedIndexChanged += delegate
            {
                if (!applyingProfile && ProfileCode() == "ja")
                {
                    ApplyProfile(false);
                    CancelReadOnce();
                    ReconfigureScreen();
                }
            };
            region.Controls.Add(japaneseDirection, 1, 0);
            panel.Controls.Add(region, 0, 1);
            TableLayoutPanel actions = Columns(0, 104);
            selectArea = MakeButton("Capture area", ChooseTarget, false);
            readOnce = MakeButton("Read once", ReadScreenOnce, false);
            DockAction(selectArea, new Padding(0, 0, 6, 2));
            DockAction(readOnce, new Padding(0, 0, 0, 2));
            actions.Controls.Add(selectArea, 0, 0);
            actions.Controls.Add(readOnce, 1, 0);
            panel.Controls.Add(actions, 0, 2);
            screenStateLabel = Note("Waiting for local language files.", muted);
            screenStateLabel.Font = new Font(Font.FontFamily, 9F);
            screenStateLabel.TextAlign = ContentAlignment.MiddleLeft;
            screenStateLabel.TextChanged += delegate { dashboardTips.SetToolTip(screenStateLabel, screenStateLabel.Text); };
            panel.Controls.Add(screenStateLabel, 0, 3);
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
            devices.SelectedIndexChanged += delegate { if (!updatingDevices && audioWanted) RestartAudio(); };
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
            ModernCard card = LightCard(paper, new Padding(19, 13, 19, 13));
            TableLayoutPanel form = Rows(44, 38, 1, 0);
            TableLayoutPanel heading = Columns(0, 145);
            heading.Controls.Add(Title("Live captions", paperInk, 20F), 0, 0);
            overlayToggle = new CaptionOption { Text = "Caption overlay", AccessibleName = "Show live caption overlay", AutoSize = false,
                Checked = true, ForeColor = paperInk, BackColor = paper, Anchor = AnchorStyles.Right, Size = new Size(142,32), Margin = Padding.Empty };
            overlayToggle.CheckedChanged += delegate { OverlayPreferenceChanged(); };
            dashboardTips.SetToolTip(overlayToggle, "Show translated screen text near its source and speech captions over other windows.");
            heading.Controls.Add(overlayToggle, 1, 0);
            form.Controls.Add(heading, 0, 0);
            TableLayoutPanel bar = Columns(0, 136);
            TableLayoutPanel options = Columns(132, 0);
            showSource = new CaptionOption { Text = "Source text", AccessibleName = "Show source text in the transcript", Checked = true,
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
            form.Controls.Add(Divider(Color.FromArgb(218, 231, 225)), 0, 2);
            Panel body = new Panel { Dock = DockStyle.Fill, BackColor = paper, Margin = new Padding(0, 13, 0, 0) };
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
            input.BackColor = Color.FromArgb(243,248,245);
            input.ForeColor = paperInk;
            input.Margin = Padding.Empty;
            Panel editor = new Panel { Dock = DockStyle.Fill, BackColor = input.BackColor, Padding = new Padding(9, 6, 5, 4), Margin = new Padding(0, 3, 0, 5) };
            editor.Paint += delegate(object sender, PaintEventArgs paint) { ControlPaint.DrawBorder(paint.Graphics, editor.ClientRectangle, input.Focused ? violet : Color.FromArgb(197,214,207), ButtonBorderStyle.Solid); };
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
            translate.BackColor = violet;
            translate.ForeColor = Color.White;
            translate.FlatAppearance.BorderColor = violet;
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
            card.BorderColor = Color.FromArgb(199, 216, 209);
            card.Padding = inset;
            return card;
        }
    }
}
