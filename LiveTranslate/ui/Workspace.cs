using System;
using System.Drawing;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed partial class MainForm
    {
        private Button copyTranscript, clearTranscript, pickLanguage;
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
            TableLayoutPanel main = Rows(68, 0, 32);
            main.Padding = new Padding(18, 5, 18, 4);
            main.BackColor = background;
            Controls.Add(main);
            TableLayoutPanel header = Columns(0, 355);
            TableLayoutPanel brand = Columns(48, 0);
            brand.Controls.Add(new DashboardGlyph(DashboardGlyph.Kind.Brand) { Size = new Size(38, 38), Anchor = AnchorStyles.Left, Margin = Padding.Empty }, 0, 0);
            brand.Controls.Add(Title("Live Translate", paperInk, 18), 1, 0);
            header.Controls.Add(brand, 0, 0);
            TableLayoutPanel tools = Columns(0, 197);
            engineBadge = Note("Checking local engine", secondaryInk);
            engineBadge.TextAlign = ContentAlignment.MiddleRight;
            engineBadge.Padding = new Padding(0, 0, 14, 0);
            tools.Controls.Add(engineBadge, 0, 0);
            TableLayoutPanel buttons = Columns(106, 0);
            Button vr = LightButton("VR captions", delegate { OpenVrCaptions(); });
            Button settings = LightButton("Settings", delegate { OpenSettings(); });
            vr.Size = new Size(101, 34);
            settings.Size = new Size(85, 34);
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

            TableLayoutPanel workspace = Columns(316, 0);
            workspace.TabIndex = 0;
            header.TabIndex = 1;
            workspace.Controls.Add(BuildCapturePanel(), 0, 0);
            TableLayoutPanel right = Rows(0, 170);
            right.Controls.Add(BuildTranscript(), 0, 0);
            right.Controls.Add(BuildComposer(), 0, 1);
            workspace.Controls.Add(right, 1, 0);
            main.Controls.Add(workspace, 0, 1);
            status = Note("Checking local language files…", secondaryInk);
            status.TextAlign = ContentAlignment.MiddleLeft;
            status.AccessibleRole = AccessibleRole.StatusBar;
            main.Controls.Add(status, 0, 2);
            Disposed += delegate { dashboardTips.Dispose(); if (writtenLanguageSetup != null) writtenLanguageSetup.Dispose(); };
            UpdateTranscriptTools();
        }

        private ModernCard BuildCapturePanel()
        {
            ModernCard rail = Card(surface);
            rail.BorderColor = surface;
            rail.Padding = new Padding(17, 13, 17, 13);
            rail.Margin = new Padding(0, 0, 14, 0);
            TableLayoutPanel form = Rows(34, 27, 39, 42, 1, 151, 1, 128, 1, 0, 56, 37);
            form.Controls.Add(Title("Capture controls", ink, 16F), 0, 0);
            TableLayoutPanel route = Columns(0, 109);
            route.Controls.Add(Title("Translate from", muted, 9.5F), 0, 0);
            Label target = Kicker("INTO ENGLISH");
            target.TextAlign = ContentAlignment.MiddleRight;
            target.ForeColor = Color.FromArgb(156, 224, 207);
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
                modeStates[index] = Note("", muted);
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
            TableLayoutPanel region = Columns(0, 136);
            regionLabel = Note("Primary display", muted);
            regionLabel.Font = new Font(Font.FontFamily, 9F);
            region.Controls.Add(regionLabel, 0, 0);
            japaneseDirection = Combo();
            japaneseDirection.AccessibleName = "Japanese text direction";
            japaneseDirection.Font = new Font(Font.FontFamily, 8.8F);
            japaneseDirection.Items.Add(new Choice("horizontal", "Horizontal Japanese"));
            japaneseDirection.Items.Add(new Choice("vertical", "Vertical Japanese"));
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
            panel.Controls.Add(CaptureHeading("PC audio + mic", DashboardGlyph.Kind.Audio, audioToggle), 0, 0);
            devices = Combo();
            devices.AccessibleName = "Audio device";
            devices.DropDownWidth = 460;
            dashboardTips.SetToolTip(devices, "Select computer playback, a microphone, or both when available.");
            devices.SelectedIndexChanged += delegate { if (!updatingDevices && audioWanted) RestartAudio(); };
            panel.Controls.Add(devices, 0, 1);
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
            TableLayoutPanel form = Rows(42, 39, 1, 0);
            TableLayoutPanel heading = Columns(0, 139);
            heading.Controls.Add(Title("Live captions", paperInk, 21F), 0, 0);
            overlayToggle = new CheckBox { Text = "Caption overlay", AccessibleName = "Show live caption overlay", AutoSize = true,
                Checked = true, ForeColor = paperInk, BackColor = Color.Transparent, Anchor = AnchorStyles.Right, Margin = Padding.Empty };
            overlayToggle.CheckedChanged += delegate { OverlayPreferenceChanged(); };
            dashboardTips.SetToolTip(overlayToggle, "Show translated screen text near its source and speech captions over other windows.");
            heading.Controls.Add(overlayToggle, 1, 0);
            form.Controls.Add(heading, 0, 0);
            TableLayoutPanel bar = Columns(0, 143);
            FlowLayoutPanel options = Flow();
            showSource = new CheckBox { Text = "Show source text", AccessibleName = "Show source text in the transcript", Checked = true,
                AutoSize = true, BackColor = Color.Transparent, ForeColor = secondaryInk, Margin = new Padding(0, 7, 14, 0), Font = new Font(Font.FontFamily, 9.5F) };
            showSource.CheckedChanged += delegate { RenderCaptions(); };
            options.Controls.Add(showSource);
            transcriptCount = Note("", secondaryInk);
            transcriptCount.AutoSize = true;
            transcriptCount.Margin = new Padding(0, 8, 0, 0);
            transcriptCount.Font = new Font(Font.FontFamily, 9F);
            options.Controls.Add(transcriptCount);
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
            form.Controls.Add(Divider(Color.FromArgb(223, 226, 237)), 0, 2);
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
            ModernCard card = LightCard(Color.FromArgb(247, 248, 252), new Padding(16, 9, 16, 10));
            card.Margin = new Padding(0, 10, 0, 0);
            TableLayoutPanel form = Rows(31, 0, 37);
            TableLayoutPanel heading = Columns(0, 64);
            heading.Controls.Add(Title("Translate text", paperInk, 12F), 0, 0);
            Button paste = LightButton("Paste", delegate
            {
                try { if (Clipboard.ContainsText()) input.Text = Clipboard.GetText(); }
                catch (Exception ex) { SetStatus(ex.Message); }
            });
            DockAction(paste, new Padding(0, 0, 0, 3));
            heading.Controls.Add(paste, 1, 0);
            form.Controls.Add(heading, 0, 0);
            input = Entry("");
            input.AccessibleName = "Text to translate";
            input.Multiline = true;
            input.AcceptsReturn = true;
            input.ScrollBars = ScrollBars.Vertical;
            input.Font = new Font(Font.FontFamily, 11F);
            input.BackColor = paper;
            input.ForeColor = paperInk;
            input.Margin = new Padding(0, 3, 0, 5);
            input.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyData == (Keys.Control | Keys.Enter)) { e.SuppressKeyPress = true; TranslateInput(); }
            };
            form.Controls.Add(input, 0, 1);
            TableLayoutPanel footer = Columns(0, 185);
            Button example = LightButton("Try example", delegate { InsertExample(); });
            example.Width = 107;
            example.Anchor = AnchorStyles.Left;
            example.Margin = Padding.Empty;
            footer.Controls.Add(example, 0, 0);
            Button translate = MakeButton("Translate to English", delegate { TranslateInput(); }, true);
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
            Send("translate", Dict("text", input.Text, "source", TextSource()));
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
            card.BorderColor = Color.FromArgb(207, 213, 226);
            card.Padding = inset;
            return card;
        }
    }
}
