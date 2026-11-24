using System;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Diagnostics;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed partial class MainForm
    {
        private Label modelActionHint;
        private Button moreWrittenLanguages;
        private Process writtenLanguageSetup;
        private readonly List<Button> modelButtons = new List<Button>();
        private ModernCard Card(Color color)
        {
            return new ModernCard
            {
                Dock = DockStyle.Fill,
                FillColor = color,
                BorderColor = border,
                Padding = new Padding(14),
                Margin = new Padding(0)
            };
        }

        private Label Note(string text, Color color)
        {
            return new Label
            {
                Text = text,
                Dock = DockStyle.Fill,
                ForeColor = color,
                BackColor = Color.Transparent,
                TextAlign = ContentAlignment.MiddleLeft,
                Margin = new Padding(0),
                AutoEllipsis = true
            };
        }

        private Label Kicker(string text)
        {
            Label label = Note(text, accent);
            label.Font = labelFont;
            return label;
        }

        private TableLayoutPanel Rows(params int[] heights)
        {
            TableLayoutPanel table = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 1,
                RowCount = heights.Length,
                Margin = new Padding(0),
                BackColor = Color.Transparent
            };
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            foreach (int height in heights)
                table.RowStyles.Add(height == 0 ? new RowStyle(SizeType.Percent, 100) : new RowStyle(SizeType.Absolute, height));
            return table;
        }

        private TableLayoutPanel Columns(int left, int right)
        {
            TableLayoutPanel table = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 2,
                RowCount = 1,
                Margin = new Padding(0),
                BackColor = Color.Transparent
            };
            table.ColumnStyles.Add(left == 0 ? new ColumnStyle(SizeType.Percent, 100) : new ColumnStyle(SizeType.Absolute, left));
            table.ColumnStyles.Add(right == 0 ? new ColumnStyle(SizeType.Percent, 100) : new ColumnStyle(SizeType.Absolute, right));
            table.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            return table;
        }

        private FlowLayoutPanel Flow()
        {
            return new FlowLayoutPanel
            {
                Dock = DockStyle.Fill,
                WrapContents = false,
                FlowDirection = FlowDirection.LeftToRight,
                Margin = new Padding(0),
                BackColor = Color.Transparent
            };
        }

        private ComboBox Combo()
        {
            return new ComboBox
            {
                Dock = DockStyle.Fill,
                DropDownStyle = ComboBoxStyle.DropDownList,
                BackColor = field,
                ForeColor = paperInk,
                FlatStyle = FlatStyle.Standard,
                Margin = new Padding(0, 0, 0, 5)
            };
        }

        private TextBox Entry(string text)
        {
            return new TextBox
            {
                Text = text,
                Dock = DockStyle.Fill,
                BackColor = field,
                ForeColor = ink,
                BorderStyle = BorderStyle.FixedSingle,
                Margin = new Padding(0, 0, 0, 5)
            };
        }

        private Button MakeButton(string text, EventHandler action, bool primary)
        {
            ModernButton button = new ModernButton
            {
                Text = text,
                Height = 32,
                Width = 143,
                FlatStyle = FlatStyle.Flat,
                BackColor = primary ? accent : field,
                ForeColor = primary ? WindowTheme.AccentInk : ink,
                Margin = new Padding(0, 0, 7, 0),
                UseVisualStyleBackColor = false
            };
            button.FlatAppearance.BorderSize = 1;
            button.FlatAppearance.BorderColor = primary ? accent : border;
            button.Click += action;
            return button;
        }

        private Button LightButton(string text, EventHandler action)
        {
            Button button = MakeButton(text, action, false);
            button.BackColor = field;
            button.ForeColor = paperInk;
            button.FlatAppearance.BorderColor = border;
            button.Font = new Font("Segoe UI", 9F);
            button.Height = 28;
            return button;
        }

        private void AddPriorityChoices(ComboBox combo, bool includeOther)
        {
            combo.Items.Add(new Choice("auto", "Auto-detect language"));
            combo.Items.Add(new Choice("zt", "Traditional Chinese  \u7e41\u9ad4\u4e2d\u6587"));
            combo.Items.Add(new Choice("zh", "Simplified Chinese  \u7b80\u4f53\u4e2d\u6587"));
            combo.Items.Add(new Choice("ko", "Korean  \ud55c\uad6d\uc5b4"));
            combo.Items.Add(new Choice("ja", "Japanese  \u65e5\u672c\u8a9e"));
            if (includeOther)
                combo.Items.Add(new Choice("other", "Other language / custom settings"));
        }

        private void FillProfiles()
        {
            string selected = ProfileCode();
            applyingProfile = true;
            try
            {
                profileSelector.Items.Clear();
                AddPriorityChoices(profileSelector, false);
                HashSet<string> added = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (Choice choice in profileSelector.Items) added.Add(choice.Code);
                added.Add("en");
                added.Add("other");
                foreach (Dictionary<string, Dictionary<string, object>> source in new[] { profiles, languageMetadata })
                    foreach (KeyValuePair<string, Dictionary<string, object>> pair in source)
                        if (added.Add(pair.Key))
                            profileSelector.Items.Add(new Choice(pair.Key, Value(pair.Value, "name")));
                profileSelector.Items.Add(new Choice("other", "Custom settings"));
                SelectCode(profileSelector, selected);
                SyncLanguageButton();
                if (activePicker != null) activePicker.SetSources(PickerSources(), ProfileCode());
            }
            finally
            {
                applyingProfile = false;
            }
        }

        private void FillCustomSources()
        {
            string selected = SelectedCode(customTextSource);
            customTextSource.Items.Clear();
            AddPriorityChoices(customTextSource, false);
            customTextSource.Items.Add(new Choice("en", "English"));
            foreach (KeyValuePair<string, Dictionary<string, object>> pair in languageMetadata)
                if (!PriorityProfile(pair.Key) && pair.Key != "en" && pair.Key != "auto")
                    customTextSource.Items.Add(new Choice(pair.Key, Value(pair.Value, "name")));
            SelectCode(customTextSource, selected);
        }

        private void RefreshReadiness()
        {
            if (profileReadiness == null) return;
            string code = ProfileCode();
            Dictionary<string, object> info;
            profiles.TryGetValue(code, out info);
            profileReadiness.Text = connected ? "Input availability" : SetupRunning() ? "Preparing language files" : RuntimeReady() ? "Checking language files" : "Set up language files";
            for (int i = 0; i < modeStates.Length; i++)
            {
                string state = ModeState(code, info, i);
                if (state == "Ready" && i == 2 && !ScreenModelsReady()) state = "Set up";
                if (state == "Ready" && i == 1 && (!SpeechModelSupportsSelection() || !speechModels.Contains(Convert.ToString(audioModel.SelectedItem)))) state = "Set up";
                string mode = LanguagePicker.Modes[i];
                modeStates[i].Text = mode + (state == "Ready" ? " ready" : state == "Set up" ? " setup" : state == "Unsupported" ? " n/a" : "");
                ((AvailabilityIndicator)modeStates[i]).SetState(state);
                modeStates[i].AccessibleName = mode + " " + state;
                string provider = i == 2 && info != null ? Value(info, "ocr_provider") : "";
                dashboardTips.SetToolTip(modeStates[i], mode + " • " + state + (provider.Length == 0 ? "" : " • " + provider));
            }
        }

        private string ModeState(string code, Dictionary<string, object> info, int index)
        {
            if (!connected) return "Checking";
            string mode = index == 0 ? "text" : index == 1 ? "speech" : "screen";
            if (code == "auto")
            {
                foreach (KeyValuePair<string, Dictionary<string, object>> pair in profiles)
                    if ((index != 2 || PriorityProfile(pair.Key)) && Flag(pair.Value, mode + "_ready"))
                        return "Ready";
                return "Set up";
            }
            if (code == "other") return "Custom";
            if (info == null) return "Checking";
            if (info.ContainsKey(mode + "_supported") && !Flag(info, mode + "_supported")) return "Unsupported";
            if (Flag(info, mode + "_ready")) return "Ready";
            return "Set up";
        }

        private void UpdateControls()
        {
            if (audioToggle == null || setupComponents == null)
                return;
            bool setup = SetupRunning(), capture = audioWanted || screenWanted;
            bool runtimeReady = connected || RuntimeReady();
            bool usable = connected && !setup && !profileBusy;
            pickLanguage.Enabled = profileSelector.Enabled = !setup && !profileBusy;
            audioToggle.Enabled = usable && devicesReady && (audioWanted || (devices.SelectedIndex >= 0 && SpeechModelSupportsSelection()));
            // A user can disarm automatic capture before the runtime or its models are ready.
            screenToggle.Enabled = !closing;
            SetSwitch(screenToggle, screenArmed);
            if (screenRegionRow != null)
                screenRegionRow.ColumnStyles[1].Width = ProfileCode() == "ja" ? Math.Max(85, japaneseDirection.PreferredHeight * 3.8F) : 0;
            devices.Enabled = usable && devicesReady;
            if (audioDeviceHint != null) {
                audioDeviceHint.Visible = !devicesReady || devices.Items.Count == 0;
                audioDeviceHint.Text = connected && devicesReady ? "No audio devices available" : "Waiting for audio devices";
            }
            UpdateTranslateAction();
            RefreshPracticeControls();
            readOnce.Enabled = usable && !oneShotPending && ScreenModelsReady() && !CaptureBounds().IsEmpty;
            readOnce.Text = oneShotPending ? "Reading..." : "Read once";
            selectArea.Enabled = !setup && !profileBusy;
            setupProfile.Enabled = !setup && !profileBusy;
            setupAll.Enabled = !setup && !profileBusy && !capture;
            moreWrittenLanguages.Enabled = !setup && !profileBusy && runtimeReady;
            modelActionHint.Text = capture ? "Pause screen and audio capture to change the starter or speech models." : "";
            setupComponents.Enabled = !setup && !profileBusy && !capture;
            foreach (Button button in modelButtons)
                button.Enabled = usable && !capture;
            setupAll.Text = setup ? "Installing..." : profileBusy ? "Downloading..." : "Set up starter languages";
            engineBadge.Text = setup ? "Preparing components" : connected ? "Local engine ready" : runtimeReady ? "Connecting to engine" : "Setup needed";
            ((EngineIndicator)engineBadge).Ready = connected && !setup;
            RefreshReadiness();
            EmptyTranscript waiting = emptyOutput as EmptyTranscript;
            if (waiting != null)
            {
                bool needsSetup = !runtimeReady && !setup;
                waiting.ShowSetup = needsSetup;
                waiting.Text = needsSetup ? "Set up your first language" : "Ready for your first caption";
                waiting.Hint = needsSetup ? "Prepare the local engine to translate on this computer." : "Turn on a capture source or paste text below.";
            }
            if (!connected && !setup)
            {
                audioStateLabel.Text = runtimeReady ? "Off. Waiting for the local engine." : "Off. Set up a language to enable listening.";
                screenStateLabel.Text = !screenArmed ? "Paused." : runtimeReady ? "Waiting for the local engine. Watching will resume automatically." : "Waiting for setup. Watching starts automatically.";
            }
            else if (connected && !devicesReady)
                audioStateLabel.Text = "Checking available audio devices...";
            else if (connected && devices.Items.Count == 0 && !audioWanted)
                audioStateLabel.Text = "No audio devices found. Refresh sources in Settings.";
            RefreshSessionUi();
        }

        private void InsertExample()
        {
            if (!String.IsNullOrWhiteSpace(input.Text))
            {
                SetStatus("Your text is still here. Clear the text box before trying an example.");
                return;
            }

            string code = TextSource();
            if (code == "zt")
                input.Text = "\u9019\u53f0\u76f8\u6a5f\u662f\u65e5\u672c\u88fd\u7684\u3002";
            else if (code == "zh")
                input.Text = "\u8fd9\u53f0\u76f8\u673a\u662f\u65e5\u672c\u5236\u9020\u7684\u3002";
            else if (code == "ko")
                input.Text = "\uc774 \uce74\uba54\ub77c\ub294 \uc77c\ubcf8\uc81c\uc785\ub2c8\ub2e4.";
            else if (code == "ja" || code == "auto")
                input.Text = "\u3053\u306e\u30ab\u30e1\u30e9\u306f\u65e5\u672c\u88fd\u3067\u3059\u3002";
            else
            {
                SetStatus("Examples are provided for the four named languages. Paste your own text for this language.");
                return;
            }

            SetStatus("Example inserted. Click Translate to English to test the selected model.");
        }

        private void InstallWrittenLanguages(object sender, EventArgs e)
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string runtime = Path.Combine(root, "runtime", "python.exe");
            string script = Path.Combine(root, "backend", "install_written_languages.py");
            try
            {
                if (writtenLanguageSetup != null && !writtenLanguageSetup.HasExited)
                {
                    MessageBox.Show(settingsForm, "The text model installer is already open.", "Text language files", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }
                if (!File.Exists(runtime) || !File.Exists(script))
                {
                    MessageBox.Show(settingsForm, "Install or repair the local components, then reopen Language files.", "Text language files", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }
                string explanation = "Download the optional NLLB text model for personal, noncommercial use?\r\n\r\n" +
                    "The installer downloads four files (601 MiB total) from the checked Hugging Face source. It verifies the pinned SHA-256 hashes and runs Microsoft Defender.\r\n\r\n" +
                    "Restart Live Translate after the installer finishes to use the new languages.";
                if (MessageBox.Show(settingsForm, explanation, "Get more text languages", MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
                if (writtenLanguageSetup != null) writtenLanguageSetup.Dispose();
                writtenLanguageSetup = null;
                writtenLanguageSetup = Process.Start(new ProcessStartInfo(runtime, "-I -B -X utf8 \"" + script + "\" --pause")
                {
                    UseShellExecute = true, WorkingDirectory = root, WindowStyle = ProcessWindowStyle.Normal
                });
            }
            catch (Exception ex)
            {
                MessageBox.Show(settingsForm, ex.Message, "Text language installer", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private string[] initialSpeechSettings, initialScreenSettings;
        private string[] SpeechSettingsValues()
        {
            return new[] { audioModel.Text, koreanDialogue.Text, audioLanguage.Text.Trim(), chunks.Value.ToString(), threads.Value.ToString() };
        }

        private string[] ScreenSettingsValues()
        {
            return new[] { ocrLanguage.Text.Trim(), tesseractPath.Text.Trim(), SelectedCode(customTextSource) };
        }

        private void RememberProcessingSettings()
        {
            initialSpeechSettings = SpeechSettingsValues();
            initialScreenSettings = ScreenSettingsValues();
        }

        private void OpenSettings()
        {
            if (settingsForm == null || settingsForm.IsDisposed)
                return;
            if (!settingsForm.Visible)
            {
                RememberProcessingSettings();
                settingsForm.Show(this);
            }
            else
                settingsForm.BringToFront();
        }

        private void BuildSettings()
        {
            settingsForm = new Form
            {
                Text = "Live Translate – Settings",
                Size = new Size(756, 750),
                MinimumSize = new Size(562, 420),
                StartPosition = FormStartPosition.CenterParent,
                AutoScaleDimensions = new SizeF(96, 96),
                AutoScaleMode = AutoScaleMode.Dpi,
                BackColor = background,
                ForeColor = paperInk,
                Font = Font,
                ShowInTaskbar = false
            };
            WindowTheme.Apply(settingsForm);
            settingsForm.FormClosing += delegate (object sender, FormClosingEventArgs e)
            {
                if (!closing && e.CloseReason == CloseReason.UserClosing)
                {
                    e.Cancel = true;
                    ApplySettings();
                }
            };
            settingsForm.Load += delegate { FitToDisplay(settingsForm); };
            TableLayoutPanel main = Rows(66, 0, 49);
            main.Padding = new Padding(14, 0, 14, 4);
            Label title = Note("Settings", paperInk);
            title.Font = new Font(Font.FontFamily, 21F, FontStyle.Bold);
            title.Padding = new Padding(5, 0, 0, 0);
            main.Controls.Add(title, 0, 0);
            settingsForm.Controls.Add(main);
            settingsTabs = new TabControl
            {
                Dock = DockStyle.Fill,
                Padding = new Point(10, 7),
                AccessibleName = "Settings sections",
                Margin = Padding.Empty
            };
            TabPage processing = SettingsPage("Audio and screen");
            TabPage files = SettingsPage("Language files");
            settingsTabs.TabPages.Add(processing);
            settingsTabs.TabPages.Add(files);
            main.Controls.Add(settingsTabs, 0, 1);
            TableLayoutPanel controls = new TableLayoutPanel
            {
                Dock = DockStyle.Top,
                ColumnCount = 2,
                RowCount = 13,
                Height = 448,
                Margin = new Padding(0)
            };
            controls.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 159));
            controls.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            foreach (int height in new[] { 25, 35, 35, 35, 35, 39, 29, 35, 35, 39, 50, 25, 31 })
                controls.RowStyles.Add(new RowStyle(SizeType.Absolute, height));
            SettingSection(controls, 0, "Speech input");
            SettingSection(controls, 6, "Text and screen");
            SettingSection(controls, 11, "Dashboard");
            audioModel = Combo();
            audioModel.Items.AddRange(new object[] { "base", "small", "medium" });
            audioModel.SelectedIndex = 0;
            AddSetting(controls, 1, "Speech model", audioModel);
            bool offersDialogue = File.Exists(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "scripts", DialogueInstaller));
            koreanDialogue = Combo();
            koreanDialogue.Items.Add("Standard");
            if (offersDialogue)
                koreanDialogue.Items.Add("NVIDIA GPU (install dialogue files first)");
            koreanDialogue.SelectedIndex = 0;
            koreanDialogue.Enabled = offersDialogue;
            koreanDialogue.SelectedIndexChanged += delegate
            {
                if (koreanDialogue.SelectedIndex == 1)
                    audioModel.SelectedItem = "small";
            };
            audioModel.SelectionChangeCommitted += delegate { speechModelChosen = true; };
            audioModel.SelectedIndexChanged += delegate
            {
                if (koreanDialogue.SelectedIndex == 1 && !Object.Equals(audioModel.SelectedItem, "small"))
                    koreanDialogue.SelectedIndex = 0;
            };
            AddSetting(controls, 2, "Korean dialogue", koreanDialogue);
            audioLanguage = Entry("auto");
            AddSetting(controls, 3, "Speech language code", audioLanguage);
            FlowLayoutPanel tuning = Flow();
            chunks = new NumericUpDown
            {
                Minimum = 3,
                Maximum = 12,
                Value = 5,
                Width = 59,
                BackColor = field,
                ForeColor = ink
            };
            threads = new NumericUpDown
            {
                Minimum = 1,
                Maximum = 8,
                Value = Math.Min(4, Math.Max(1, Environment.ProcessorCount)),
                Width = 59,
                BackColor = field,
                ForeColor = ink
            };
            tuning.Controls.Add(chunks);
            tuning.Controls.Add(new Label { Text = "sec / phrase", AutoSize = true, ForeColor = muted, Margin = new Padding(4, 5, 15, 0) });
            tuning.Controls.Add(threads);
            chunks.AccessibleName = "Seconds per speech phrase";
            threads.AccessibleName = "Speech recognition CPU threads";
            tuning.Controls.Add(new Label { Text = "CPU threads", AutoSize = true, ForeColor = muted, Margin = new Padding(4, 5, 0, 0) });
            AddSetting(controls, 4, "Performance", tuning);
            customTextSource = Combo();
            AddPriorityChoices(customTextSource, false);
            customTextSource.Items.Add(new Choice("en", "English"));
            customTextSource.SelectedIndex = 0;
            AddSetting(controls, 7, "Custom text source", customTextSource);
            ocrLanguage = Entry("");
            AddSetting(controls, 8, "OCR language code", ocrLanguage);
            tesseractPath = Entry("");
            TableLayoutPanel path = Columns(0, 85);
            path.Controls.Add(tesseractPath, 0, 0);
            Button browse = MakeButton("Browse", delegate
            {
                using (OpenFileDialog picker = new OpenFileDialog
                {
                    Filter = "Optional external OCR engine|tesseract.exe|Executable|*.exe",
                    Title = "Choose an optional external Tesseract engine"
                }

                )
                {
                    if (picker.ShowDialog(settingsForm) == DialogResult.OK)
                        tesseractPath.Text = picker.FileName;
                }
            }, false);
            browse.Dock = DockStyle.Fill;
            browse.Margin = new Padding(6, 0, 0, 5);
            path.Controls.Add(browse, 1, 0);
            tesseractPath.AccessibleName = "Optional external OCR executable";
            AddSetting(controls, 9, "External OCR (optional)", path);
            FlowLayoutPanel deviceActions = Flow();
            Button refresh = MakeButton("Refresh audio sources", delegate
            {
                Send("devices", null);
            }, false);
            refresh.Width = 185;
            deviceActions.Controls.Add(refresh);
            AddSetting(controls, 5, "Audio devices", deviceActions);
            CheckBox keepMainOnTop = new CheckBox
            {
                Text = "Keep the dashboard on top",
                ForeColor = ink, AutoSize = true, Dock = DockStyle.Left
            };
            keepMainOnTop.CheckedChanged += delegate { TopMost = keepMainOnTop.Checked; };
            AddSetting(controls, 12, "Window", keepMainOnTop);
            Label tip = Note("Auto-detect watches Chinese, Korean and Japanese on screen. For other scripts, choose the source language on the dashboard.", muted);
            tip.Font = new Font("Segoe UI", 9F);
            controls.Controls.Add(tip, 0, 10);
            controls.SetColumnSpan(tip, 2);
            TableLayoutPanel fileControls = Rows(42, 65, 65, 43, 56, 56, 29, 0);
            setupComponents = MakeButton("Install / repair components", delegate
            {
                LaunchSetup(null, null);
            }, false);
            TableLayoutPanel componentRow = Columns(0, 111);
            setupComponents.Dock = DockStyle.Fill;
            componentRow.Controls.Add(setupComponents, 0, 0);
            Button reconnect = MakeButton("Reconnect", delegate
            {
                StartWorker();
            }, false);
            reconnect.Dock = DockStyle.Fill;
            reconnect.Margin = new Padding(7, 0, 0, 5);
            componentRow.Controls.Add(reconnect, 1, 0);
            fileControls.Controls.Add(componentRow, 0, 0);
            setupAll = MakeButton("Set up starter languages", delegate { StartInstall("install_all_profiles", null); }, true);
            fileControls.Controls.Add(ModelSetting("Starter languages", "Chinese (both scripts), Korean and Japanese. Includes speech and screen recognition.", setupAll), 0, 1);
            moreWrittenLanguages = MakeButton("Get more text languages…", InstallWrittenLanguages, false);
            fileControls.Controls.Add(ModelSetting("Multilingual text", "Optional 601 MiB model for personal, noncommercial use.", moreWrittenLanguages), 0, 2);

            ComboBox packSpeech = Combo();
            packSpeech.AccessibleName = "Optional speech model package";
            packSpeech.Items.Add("Quality speech · 1.26 GiB · noncommercial");
            if (offersDialogue) packSpeech.Items.Add("Korean dialogue · NVIDIA GPU · 3.53 GB");
            packSpeech.SelectedIndex = 0;
            Button speech = MakeButton("Set up speech", delegate
            {
                if (packSpeech.SelectedIndex == 1) LaunchComponentSetup(null, null, ComponentSetup.KoreanDialogue);
                else LaunchSetup(null, null, true);
            }, false);
            modelButtons.Add(speech);
            fileControls.Controls.Add(DownloadRow(packSpeech, speech, "Optional speech"), 0, 3);

            Button import = MakeButton("Import .argosmodel", delegate
            {
                using (OpenFileDialog picker = new OpenFileDialog { Filter = "Argos language pack|*.argosmodel", Title = "Import a local language pack" })
                    if (picker.ShowDialog(settingsForm) == DialogResult.OK)
                        Send("import_pack", Dict("path", picker.FileName));
            }, false);
            modelButtons.Add(import);
            fileControls.Controls.Add(ModelSetting("Local text pack", "Use a compatible language file you already have.", import), 0, 4);
            Button screenFiles = MakeButton("OCR settings", delegate
            {
                settingsTabs.SelectedIndex = 0;
                tesseractPath.Focus();
            }, false);
            fileControls.Controls.Add(ModelSetting("Screen recognition", "Choose your own OCR installation in Audio and screen.", screenFiles), 0, 5);
            modelActionHint = Note("", accent);
            modelActionHint.Font = new Font(Font.FontFamily, 9F);
            fileControls.Controls.Add(modelActionHint, 0, 6);
            packSummary = Note("Set up the starter languages or add an optional model for more inputs.", muted);
            packSummary.Font = new Font("Segoe UI", 9F);
            fileControls.Controls.Add(packSummary, 0, 7);
            AddSettingsBody(processing, "Recognition", "Choose a speech model and tune recognition. Select Other language on the dashboard to edit language codes.", controls, 448);
            AddSettingsBody(files, "Language files", "Install a starter set, add an optional model or import a file from your computer.", fileControls, 440);
            TableLayoutPanel footer = Columns(0, 111);
            footer.Padding = new Padding(5, 6, 2, 2);
            footer.Controls.Add(Note("Audio and screen changes apply when you close Settings.", secondaryInk), 0, 0);
            Button apply = MakeButton("Done", delegate
            {
                ApplySettings();
            }, true);
            apply.Dock = DockStyle.Fill;
            apply.Margin = new Padding(6, 1, 0, 2);
            StyleSettingControl(apply);
            settingsForm.CancelButton = apply;
            footer.Controls.Add(apply, 1, 0);
            main.Controls.Add(footer, 0, 2);
        }

        private TabPage SettingsPage(string name)
        {
            return new TabPage(name) { BackColor = surface, ForeColor = paperInk,
                Padding = new Padding(16, 10, 16, 10), AutoScroll = true };
        }

        private void SettingSection(TableLayoutPanel table, int row, string name)
        {
            var heading = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1, Margin = Padding.Empty };
            heading.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            heading.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            var label = new Label { Text = name, AutoSize = true, Anchor = AnchorStyles.Left, Font = new Font(Font, FontStyle.Bold),
                ForeColor = paperInk, Margin = new Padding(0, 0, 10, 0) };
            var rule = new Panel { Height = 1, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = Padding.Empty,
                BackColor = border };
            heading.Controls.Add(label, 0, 0); heading.Controls.Add(rule, 1, 0);
            table.Controls.Add(heading, 0, row); table.SetColumnSpan(heading, 2);
        }

        private void AddSettingsBody(TabPage page, string heading, string description, Control content, int height)
        {
            var layout = Rows(32, 51, height);
            layout.Dock = DockStyle.Top;
            if (height > 0) layout.Height = 83 + height;
            else
            {
                layout.AutoSize = true;
                layout.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                layout.RowStyles[2].SizeType = SizeType.AutoSize;
            }
            var title = Note(heading, paperInk);
            title.Font = new Font(Font.FontFamily, 15F, FontStyle.Bold);
            var blurb = Note(description, secondaryInk);
            blurb.TextAlign = ContentAlignment.TopLeft;
            blurb.Padding = new Padding(0, 3, 1, 0);
            content.Dock = DockStyle.Fill;
            layout.Controls.Add(title, 0, 0);
            layout.Controls.Add(blurb, 0, 1);
            layout.Controls.Add(content, 0, 2);
            StyleSettingControl(layout);
            page.Controls.Add(layout);
        }

        private void StyleSettingControl(Control control)
        {
            Button button = control as Button;
            bool contrast = SystemInformation.HighContrast;
            if (button != null)
            {
                bool primary = button.BackColor == accent;
                button.BackColor = primary ? accent : field;
                button.ForeColor = primary ? WindowTheme.AccentInk : ink;
                button.FlatAppearance.BorderColor = primary ? accent : border;
            }
            else if (control is TextBox || control is ComboBox || control is NumericUpDown)
            {
                control.ForeColor = ink;
                control.BackColor = field;
                control.HandleCreated += delegate { WindowTheme.ApplyControl(control); };
            }
            else if (control is Label || control is CheckBox)
            {
                control.ForeColor = contrast ? SystemColors.WindowText : control.ForeColor == muted ? muted : control.ForeColor == accent ? accent : ink;
            }
            foreach (Control child in control.Controls) StyleSettingControl(child);
        }

        private Control ModelSetting(string name, string description, Button action)
        {
            TableLayoutPanel row = Columns(0, 196);
            TableLayoutPanel text = Rows(24, 0);
            text.Controls.Add(Title(name, ink, 10F), 0, 0);
            Label hint = Note(description, muted);
            hint.Font = new Font(Font.FontFamily, 9F);
            hint.TextAlign = ContentAlignment.TopLeft;
            hint.Padding = new Padding(0, 0, 7, 0);
            text.Controls.Add(hint, 0, 1);
            row.Controls.Add(text, 0, 0);
            action.Anchor = AnchorStyles.Right;
            action.Size = new Size(190, 34);
            action.Margin = Padding.Empty;
            row.Controls.Add(action, 1, 0);
            return row;
        }

        private void AddSetting(TableLayoutPanel table, int row, string label, Control control)
        {
            Label name = Note(label, muted);
            name.TextAlign = ContentAlignment.TopLeft;
            name.Padding = new Padding(0, 4, 7, 0);
            if (String.IsNullOrEmpty(control.AccessibleName)) control.AccessibleName = label;
            control.TabIndex = row;
            table.Controls.Add(name, 0, row);
            table.Controls.Add(control, 1, row);
        }

        private TableLayoutPanel DownloadRow(Control value, Button download, string label)
        {
            TableLayoutPanel table = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 3,
                Margin = new Padding(0)
            };
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 112));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            table.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 170));
            Label name = Note(label, muted);
            name.Padding = new Padding(0, 5, 0, 0);
            table.Controls.Add(name, 0, 0);
            table.Controls.Add(value, 1, 0);
            download.Dock = DockStyle.Fill;
            download.Margin = new Padding(7, 0, 0, 5);
            table.Controls.Add(download, 2, 0);
            return table;
        }
    }
}
