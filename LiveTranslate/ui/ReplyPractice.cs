using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed partial class MainForm
    {
        private sealed class PracticeWindow : Form
        {
            private const string CaptureMarker = "LiveTranslate.ReplyPractice";
            protected override void OnHandleCreated(EventArgs e)
            {
                base.OnHandleCreated(e);
                SetSampleProperty(Handle, CaptureMarker, new IntPtr(1));
            }
            protected override void DestroyHandle()
            {
                if (IsHandleCreated) RemoveSampleProperty(Handle, CaptureMarker);
                base.DestroyHandle();
            }
        }
        private static readonly string[] PracticePriorities = { "ja", "ko", "zh", "zt" };
        private static readonly string[] PracticeExamples = {
            "Hello", "Thank you", "Please say that again", "I don't understand", "Can you speak more slowly?"
        };
        private readonly List<string> practiceTargets = new List<string>();
        private Form practiceWindow;
        private ComboBox practiceTarget, practiceExamples;
        private TextBox practiceDraft;
        private RichTextBox practiceTranslation, practiceReading, practiceNote;
        private Label practiceStatus, practiceScheme;
        private Button practiceAction, practiceCopyTranslation, practiceCopyReading;
        private bool practiceModelReady, fillingPracticeTargets;
        private int practicePending, practiceRevision, practiceSentRevision;
        private string practiceFeedback = "";

        private void OpenReplyPractice()
        {
            if (practiceWindow == null || practiceWindow.IsDisposed) BuildReplyPractice();
            if (!practiceWindow.Visible) practiceWindow.Show(this);
            if (practiceWindow.WindowState == FormWindowState.Minimized) practiceWindow.WindowState = FormWindowState.Normal;
            practiceWindow.Activate();
            practiceDraft.Focus();
        }

        private void BuildReplyPractice()
        {
            practiceWindow = new PracticeWindow {
                Name = "ReplyPractice", Text = "LiveTranslate · Reply practice", Size = new Size(660, 710),
                MinimumSize = new Size(470, 430), StartPosition = FormStartPosition.CenterParent,
                AutoScaleDimensions = new SizeF(96,96), AutoScaleMode = AutoScaleMode.Dpi,
                BackColor = WindowTheme.Background, ForeColor = WindowTheme.Ink, Font = Font, ShowInTaskbar = false
            };
            WindowTheme.Apply(practiceWindow);
            practiceWindow.Load += delegate { FitToDisplay(practiceWindow); };
            practiceWindow.FormClosed += delegate { practiceRevision++; practicePending = 0; practiceFeedback = ""; };
            Panel scroll = new Panel { Dock = DockStyle.Fill, AutoScroll = true, Padding = new Padding(17, 10, 17, 12) };
            TableLayoutPanel layout = Rows(43, 33, 72, 172, 245, 66);
            layout.Dock = DockStyle.Top;
            layout.AutoSize = true;
            layout.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            scroll.Controls.Add(layout);
            practiceWindow.Controls.Add(scroll);
            layout.Controls.Add(Title("Reply practice", paperInk, 21F), 0, 0);
            layout.Controls.Add(Note("Turn an English reply into a phrase you can say aloud.", secondaryInk), 0, 1);

            TableLayoutPanel pickers = Columns(0, 0);
            pickers.ColumnStyles[0].Width = 47;
            pickers.ColumnStyles[1].Width = 53;
            TableLayoutPanel targetGroup = Rows(24, 0);
            targetGroup.Margin = new Padding(0, 0, 10, 0);
            targetGroup.Controls.Add(Title("Reply language", paperInk, 10F), 0, 0);
            practiceTarget = Combo();
            practiceTarget.AccessibleName = "Reply language";
            practiceTarget.AutoCompleteSource = AutoCompleteSource.ListItems;
            practiceTarget.AutoCompleteMode = AutoCompleteMode.SuggestAppend;
            targetGroup.Controls.Add(practiceTarget, 0, 1);
            pickers.Controls.Add(targetGroup, 0, 0);
            TableLayoutPanel exampleGroup = Rows(24, 0);
            exampleGroup.Controls.Add(Title("Starter phrase", paperInk, 10F), 0, 0);
            practiceExamples = Combo();
            practiceExamples.AccessibleName = "Choose a starter phrase";
            practiceExamples.Items.Add("Choose a phrase…");
            practiceExamples.Items.AddRange(PracticeExamples);
            practiceExamples.SelectedIndex = 0;
            exampleGroup.Controls.Add(practiceExamples, 0, 1);
            pickers.Controls.Add(exampleGroup, 1, 0);
            layout.Controls.Add(pickers, 0, 2);

            ModernCard draftCard = LightCard(paper, new Padding(14, 10, 14, 12));
            draftCard.Margin = new Padding(0, 0, 0, 10);
            TableLayoutPanel draftLayout = Rows(28, 0, 40);
            draftLayout.Controls.Add(Title("Your English reply", paperInk, 13F), 0, 0);
            practiceDraft = new ThemedTextBox { Multiline = true, AcceptsReturn = true, MaxLength = 500, Dock = DockStyle.Fill,
                AccessibleName = "Your English reply, 500 characters maximum", BackColor = WindowTheme.Field,
                ForeColor = WindowTheme.Ink, Font = new Font(Font.FontFamily, 12F), ScrollBars = ScrollBars.Vertical,
                BorderStyle = BorderStyle.FixedSingle, Margin = new Padding(0, 4, 0, 7) };
            practiceDraft.HandleCreated += delegate { WindowTheme.ApplyControl(practiceDraft); };
            draftLayout.Controls.Add(practiceDraft, 0, 1);
            TableLayoutPanel runRow = Columns(0, 145);
            runRow.Controls.Add(Note("Ctrl+Enter to translate", secondaryInk), 0, 0);
            practiceAction = MakeButton("Translate reply", delegate { SubmitPracticeReply(); }, true);
            DockAction(practiceAction, new Padding(0, 1, 0, 1));
            runRow.Controls.Add(practiceAction, 1, 0);
            draftLayout.Controls.Add(runRow, 0, 2);
            draftCard.Controls.Add(draftLayout);
            layout.Controls.Add(draftCard, 0, 3);

            ModernCard resultCard = LightCard(paper, new Padding(14, 7, 14, 9));
            TableLayoutPanel result = Rows(30, 0, 1, 30, 0, 60);
            TableLayoutPanel translatedHeading = Columns(0, 64);
            translatedHeading.Controls.Add(Title("Translated reply", paperInk, 13F), 0, 0);
            practiceCopyTranslation = LightButton("Copy", delegate { CopyPracticeField(practiceTranslation); });
            practiceCopyTranslation.AccessibleName = "Copy translated reply";
            DockAction(practiceCopyTranslation, new Padding(0, 2, 0, 2));
            translatedHeading.Controls.Add(practiceCopyTranslation, 1, 0);
            result.Controls.Add(translatedHeading, 0, 0);
            practiceTranslation = PracticeOutput("Translated reply", paperInk, 14F);
            result.Controls.Add(practiceTranslation, 0, 1);
            result.Controls.Add(Divider(WindowTheme.Border), 0, 2);
            TableLayoutPanel readingHeading = Columns(0, 64);
            practiceScheme = Title("Phonetic spelling", paperInk, 11F);
            practiceScheme.AutoEllipsis = true;
            readingHeading.Controls.Add(practiceScheme, 0, 0);
            practiceCopyReading = LightButton("Copy", delegate { CopyPracticeField(practiceReading); });
            practiceCopyReading.AccessibleName = "Copy pronunciation";
            DockAction(practiceCopyReading, new Padding(0, 2, 0, 2));
            readingHeading.Controls.Add(practiceCopyReading, 1, 0);
            result.Controls.Add(readingHeading, 0, 3);
            practiceReading = PracticeOutput("Phonetic spelling", WindowTheme.Purple, 12F);
            result.Controls.Add(practiceReading, 0, 4);
            practiceNote = PracticeOutput("Pronunciation guidance and approximate sounds", secondaryInk, 9.5F);
            result.Controls.Add(practiceNote, 0, 5);
            resultCard.Controls.Add(result);
            layout.Controls.Add(resultCard, 0, 4);

            TableLayoutPanel footer = Columns(0, 110);
            practiceStatus = Note("", secondaryInk);
            practiceStatus.AccessibleRole = AccessibleRole.StatusBar;
            practiceStatus.Margin = new Padding(0, 0, 9, 0);
            footer.Controls.Add(practiceStatus, 0, 0);
            Button setup = LightButton("Language files", delegate {
                OpenSettings();
                settingsTabs.SelectedIndex = 1;
                moreWrittenLanguages.Focus();
            });
            setup.Size = new Size(108, 32);
            setup.Anchor = AnchorStyles.Right;
            footer.Controls.Add(setup, 1, 0);
            layout.Controls.Add(footer, 0, 5);
            FillPracticeTargets(ProfileCode());
            practiceTarget.SelectedIndexChanged += delegate { if (!fillingPracticeTargets) PracticeDraftChanged(); };
            practiceDraft.TextChanged += delegate { PracticeDraftChanged(); };
            practiceDraft.KeyDown += delegate(object sender, KeyEventArgs args) {
                if (args.KeyData == (Keys.Control | Keys.Enter)) { args.SuppressKeyPress = true; SubmitPracticeReply(); }
            };
            practiceExamples.SelectedIndexChanged += delegate {
                if (practiceExamples.SelectedIndex > 0) {
                    practiceDraft.Text = (string)practiceExamples.SelectedItem;
                    practiceDraft.SelectionStart = practiceDraft.TextLength;
                    practiceExamples.SelectedIndex = 0;
                    practiceDraft.Focus();
                }
            };
            RefreshPracticeControls();
        }

        private static RichTextBox PracticeOutput(string name, Color color, float size)
        {
            var output = new RichTextBox { AccessibleName = name, Dock = DockStyle.Fill, ReadOnly = true,
                DetectUrls = false, BackColor = WindowTheme.Card, ForeColor = WindowTheme.HighContrast ? SystemColors.WindowText : color, Font = new Font("Segoe UI", size),
                WordWrap = true, HideSelection = false, BorderStyle = BorderStyle.None,
                Margin = new Padding(0, 3, 0, 3), ScrollBars = RichTextBoxScrollBars.Vertical };
            output.HandleCreated += delegate { WindowTheme.ApplyControl(output); };
            return output;
        }

        private void UpdateReplyTargets(Dictionary<string,object> message)
        {
            practiceModelReady = Flag(message, "multilingual_text_ready");
            List<string> codes = new List<string>();
            foreach (object item in Items(message, "reply_targets"))
                if (item is string) codes.Add((string)item);
            bool changed = !String.Equals(String.Join("|", codes.ToArray()), String.Join("|", practiceTargets.ToArray()), StringComparison.Ordinal);
            if (changed) {
                practiceTargets.Clear();
                practiceTargets.AddRange(codes);
                if (practiceWindow != null && !practiceWindow.IsDisposed) FillPracticeTargets(SelectedCode(practiceTarget));
            }
        }

        private void FillPracticeTargets(string preferred)
        {
            fillingPracticeTargets = true;
            practiceTarget.BeginUpdate();
            try {
                practiceTarget.Items.Clear();
                foreach (string code in PracticePriorities)
                    practiceTarget.Items.Add(new Choice(code, ProfileName(code)));
                List<Choice> rest = new List<Choice>();
                foreach (string code in practiceTargets)
                    if (Array.IndexOf(PracticePriorities, code) < 0) rest.Add(new Choice(code, ProfileName(code)));
                rest.Sort(delegate(Choice a, Choice b) { return String.Compare(a.Name,b.Name,StringComparison.CurrentCultureIgnoreCase); });
                foreach (Choice choice in rest) practiceTarget.Items.Add(choice);
                practiceTarget.SelectedIndex = 0;
                foreach (Choice choice in practiceTarget.Items)
                    if (choice.Code == preferred) { practiceTarget.SelectedItem = choice; break; }
            } finally { practiceTarget.EndUpdate(); fillingPracticeTargets = false; }
        }

        private void PracticeDraftChanged()
        {
            practiceRevision++;
            practiceTranslation.Clear();
            practiceReading.Clear();
            practiceScheme.Text = "Phonetic spelling";
            practiceNote.Text = "";
            practiceFeedback = "";
            RefreshPracticeControls();
        }

        private void ResetPracticeConnection()
        {
            practiceModelReady = false;
            practicePending = 0;
            practiceFeedback = "";
            RefreshPracticeControls();
        }

        private void RefreshPracticeControls()
        {
            if (practiceWindow == null || practiceWindow.IsDisposed || practiceAction == null) return;
            bool ready = connected && !profileBusy && !SetupRunning();
            bool starterTarget = Array.IndexOf(PracticePriorities, SelectedCode(practiceTarget)) >= 0;
            practiceAction.Enabled = ready && practicePending == 0 && !String.IsNullOrWhiteSpace(practiceDraft.Text)
                && (starterTarget || practiceModelReady);
            practiceAction.Text = practicePending == 0 ? "Translate reply" : "Translating…";
            practiceCopyTranslation.Enabled = practiceTranslation.TextLength > 0;
            practiceCopyReading.Enabled = practiceReading.TextLength > 0;
            practiceNote.TabStop = practiceNote.TextLength > 0;
            string message = !ready ? "Waiting for the local translation engine." :
                practicePending != 0 ? "Preparing your reply…" : practiceFeedback;
            if (message == "")
                message = practiceModelReady ? "Replies stay on this PC. Read your reply aloud when ready." :
                    starterTarget ? "Starter phrases are ready. Add the multilingual text model in Language files for custom replies." :
                    "Add the multilingual text model in Language files to practice this language.";
            if (practiceStatus.Text != message) practiceStatus.Text = message;
        }

        private void SubmitPracticeReply()
        {
            if (!practiceAction.Enabled) return;
            PracticeDraftChanged();
            if (Send("practice_reply", Dict("text", practiceDraft.Text.Trim(), "target", SelectedCode(practiceTarget)))) {
                practicePending = requestId;
                practiceSentRevision = practiceRevision;
            } else practiceFeedback = "Could not reach the translation engine. Try again after it reconnects.";
            RefreshPracticeControls();
        }

        private void FinishPracticeReply(int id, Dictionary<string,object> message)
        {
            if (id != practicePending) return;
            practicePending = 0;
            if (practiceWindow == null || practiceWindow.IsDisposed) return;
            if (practiceRevision == practiceSentRevision) {
                if (Value(message, "type") == "error") practiceFeedback = Value(message, "message");
                else if (Value(message, "target") == SelectedCode(practiceTarget)) {
                    practiceTranslation.Text = Value(message, "text");
                    practiceReading.Text = Value(message, "pronunciation");
                    string scheme = Value(message, "pronunciation_scheme");
                    practiceScheme.Text = scheme == "" ? "Phonetic spelling" : "Phonetic spelling · " + scheme;
                    practiceNote.Text = Value(message, "pronunciation_note");
                    if (practiceReading.TextLength == 0 && practiceNote.Text == "")
                        practiceNote.Text = "A pronunciation guide is unavailable for this reply.";
                    practiceFeedback = Value(message, "method") == "phrasebook" ? "Starter phrase ready to practice." : "Reply ready to practice.";
                }
            }
            RefreshPracticeControls();
        }

        private void CopyPracticeField(RichTextBox field)
        {
            if (field.TextLength == 0) return;
            try { Clipboard.SetText(field.Text); practiceFeedback = "Copied."; }
            catch (System.Runtime.InteropServices.ExternalException) { practiceFeedback = "Clipboard is busy. Try again."; }
            RefreshPracticeControls();
        }
    }
}
