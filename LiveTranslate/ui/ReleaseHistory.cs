using System;
using System.Drawing;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class ReleaseNote
    {
        public readonly string Version;
        public readonly string Title;
        public readonly string[] Changes;

        public ReleaseNote(string version, string title, params string[] changes)
        {
            Version = version;
            Title = title;
            Changes = changes;
        }

        public override string ToString() { return Version; }
    }

    internal static class ReleaseHistory
    {
        // Keep the newest release first. These notes ship with the application
        // so the installed release history is also available offline.
        internal static readonly ReleaseNote[] Releases = {
            new ReleaseNote("0.7.2", "Capture area menu no longer closes with an error",
                "Fixed the disposed ContextMenuStrip error when choosing a display or drawing a capture area. The capture menu now lives with the dashboard, and selection actions wait for menu dismissal to finish.",
                "Canceling a drawn area retains the previous target. Closing the dashboard during a drawing also closes its selector safely.",
                "Reopening minimized Settings restores the window without losing pending edits. The floating caption footer now identifies a manual screen read while automatic capture is paused.",
                "The capture popup follows the dark app theme, with system rendering retained for high contrast."),
            new ReleaseNote("0.7.1", "Smoother dark controls",
                "Removed bright Windows surfaces from audio and language selectors, settings tabs, field outlines, numeric controls and scrollbars. Surfaces now follow the app's dark tones, with clear keyboard focus.",
                "Kept native device selection, keyboard input, scrolling and accessibility behavior. The styling applies only to LiveTranslate; Windows preferences are unchanged."),
            new ReleaseNote("0.7.0", "A new translation workspace",
                "A dark sidebar opens Live session, Session history, Audio setup and Settings. Moving between pages keeps the current capture session and transcript.",
                "Pause translation remembers active inputs; End session stops capture while keeping captions. Save transcript exports the current session only when you choose a file.",
                "The separate Windows captions window shows original text and English with pinning, pause and dashboard controls. Screen reading, pasted text, reply practice and signed public GitHub updates remain available.",
                "Major feature or interface releases use 0.x.0; patches for this series use 0.7.1, 0.7.2 and onward."),
            new ReleaseNote("0.6.11", "Fewer false screen captions",
                "Automatic full-display reading checks short text at its original screen position and rejects isolated toolbar symbols and unsupported fragments.",
                "Added checks against clothing-like patterns and textured backgrounds. These reduce false captions; difficult text over patterns can still be missed or misread.",
                "Short-label checks resume across unchanged frames when their work budget is reached. Choose a specific language or capture area for an ambiguous one-character label."),
            new ReleaseNote("0.6.10", "Updates through GitHub Releases",
                "Check for updates uses the official LiveTranslate GitHub release channel. Old local feed choices no longer control which version is offered.",
                "Removed local manifest selection and bundled release fallback. Connection failures show an actionable error instead of reporting a local version as current."),
            new ReleaseNote("0.6.9", "Reliable first-run verification and update checks",
                "Check for updates looks for a published GitHub release. If it cannot reach one, the app can show the version in its signed local feed and explain what happened on GitHub.",
                "Existing custom update sources remain selectable under Settings, Updates. You can also choose Automatic updates to return to the project's release channel.",
                "Fixed a Windows setup error that stopped the offline model verifier before it could run. Existing model files can be checked locally."),
            new ReleaseNote("0.6.8", "Application folders and release history",
                "Open LiveTranslate.exe from the application folder. Setup scripts, configuration files and documentation now have separate folders.",
                "Open Settings, choose Updates and select Changelog to read the notes for this or an earlier version."),
            new ReleaseNote("0.6.7", "Reply practice and pronunciation",
                "Practice replies in Japanese, Korean, Simplified Chinese or Traditional Chinese. Starter phrases show the translation, a romanized reading and an approximate English sound cue.",
                "The optional multilingual writing model can translate custom replies. Pronunciation guidance depends on the language and wording.",
                "A later installer refresh for this version added graphical Windows setup, first-run preparation and a per-user uninstall entry."),
            new ReleaseNote("0.6.6", "Caption reading and desktop controls",
                "The transcript pauses automatic scrolling while you select or read an earlier caption. Return to the bottom to follow new captions again.",
                "Long captions advance through the PC VR caption window in readable sections. A disconnected display pauses screen capture until it returns or you choose another area."),
            new ReleaseNote("0.6.5", "Spoken English and signed updates",
                "Hear accepted speech translations through an installed English voice. Choose the output device, rate and volume in Settings.",
                "Added a per-user Windows installer and support for signed updates from the project's GitHub Releases feed."),
            new ReleaseNote("0.6.4", "More languages and a PC VR caption window",
                "The searchable language picker puts Asian languages first and shows which inputs are available for each language.",
                "An optional writing model expanded translation to 201 non-English language and script entries. Its license permits noncommercial use.",
                "A separate captions window can be selected in a PC headset's desktop view and pinned when the VR runtime supports it."),
            new ReleaseNote("0.6.3", "In-app updates",
                "Check for an update, download it and restart from Settings while keeping installed language models.",
                "Added a release publisher and local release server for distributing updates."),
            new ReleaseNote("0.6.2", "Steadier captions",
                "The source update addressed repeated speech changing wording, including a phrase heard through both audio inputs.",
                "Screen caption changes improved tracking through brief recognition gaps and background matching around replaced text."),
            new ReleaseNote("0.6.1", "Text overlays that fit the source",
                "Screen translations fit inside the detected word or phrase, with long translations wrapping or paging in place.",
                "The overlay lets plain or gently shaded backgrounds show through and uses a solid fill where it cannot reliably reconstruct the background."),
            new ReleaseNote("0.6", "Optional dialogue models",
                "An optional quality pack added another speech recognizer, a larger Whisper model and a translator for spoken phrases.",
                "Optional Korean dialogue setup supported compatible NVIDIA GPUs. The bundled setup instructions document license and storage requirements."),
            new ReleaseNote("0.5", "Captions at the translated text",
                "Choose a display or draw a capture area. Screen captions follow their source text, while speech captions appear near the bottom of the display.",
                "Computer + microphone captures both sides of a call. The app starts capturing while the speech model warms up to help with short replies."),
            new ReleaseNote("0.4", "Offline setup and English filtering",
                "The offline edition bundled the Windows runtime and starter models, checked the files locally and tested translations during preparation.",
                "Screen watching covered the primary display and filtered English-only input before showing captions."),
            new ReleaseNote("0.3", "A single translation dashboard",
                "The dashboard brought the language selector, pasted text, screen reading, audio controls and captions together.",
                "Screen watching and auto-listen could be switched independently. Setup could prepare all four starter profiles at once."),
            new ReleaseNote("0.2", "Four starter language profiles",
                "Language setup offered Traditional Chinese, Simplified Chinese, Korean and Japanese from the Windows app.",
                "Japanese screen reading supported horizontal text and upright vertical columns."),
            new ReleaseNote("0.1", "First Windows prototype",
                "Translated pasted text, selected screen text, microphone speech and computer playback into English.",
                "Speech and text translation used local model files after the initial setup.")
        };
    }

    internal sealed class ReleaseHistoryWindow : Form
    {
        private readonly ComboBox versions = new ThemedComboBox();
        private readonly Label title = new Label();
        private readonly TextBox notes = new ThemedTextBox();
        private readonly Font titleFont;

        internal ReleaseHistoryWindow(Font textFont)
        {
            Name = "ReleaseHistory";
            Text = "LiveTranslate changelog";
            Font = textFont;
            AutoScaleDimensions = new SizeF(96F, 96F);
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(550, 338);
            MinimumSize = new Size(340, 270);
            StartPosition = FormStartPosition.CenterParent;
            ShowInTaskbar = false;
            MinimizeBox = false;
            BackColor = WindowTheme.Background;
            ForeColor = WindowTheme.Ink;
            WindowTheme.Apply(this);

            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18),
                ColumnCount = 1, RowCount = 5 };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            Controls.Add(layout);

            layout.Controls.Add(new Label { Text = "&Version", AutoSize = true, TabIndex = 0 }, 0, 0);
            versions.Name = "ReleaseVersion";
            versions.AccessibleName = "Release version";
            versions.DropDownStyle = ComboBoxStyle.DropDownList;
            versions.BackColor = WindowTheme.Field;
            versions.ForeColor = WindowTheme.Ink;
            versions.HandleCreated += delegate { WindowTheme.ApplyControl(versions); };
            versions.MaxDropDownItems = 14;
            versions.Width = 128;
            versions.TabIndex = 1;
            layout.Controls.Add(versions, 0, 1);

            titleFont = new Font(Font.FontFamily, Font.SizeInPoints + 4F, FontStyle.Bold);
            title.Font = titleFont;
            title.Dock = DockStyle.Fill;
            title.AutoSize = true;
            title.Margin = new Padding(3, 12, 3, 6);
            layout.Controls.Add(title, 0, 2);

            notes.Name = "ReleaseNotes";
            notes.AccessibleName = "Changes in the selected version";
            notes.Dock = DockStyle.Fill;
            notes.BorderStyle = BorderStyle.None;
            notes.Multiline = true;
            notes.ReadOnly = true;
            notes.ScrollBars = ScrollBars.Vertical;
            notes.BackColor = WindowTheme.Background;
            notes.ForeColor = WindowTheme.Muted;
            notes.HandleCreated += delegate { WindowTheme.ApplyControl(notes); };
            notes.TabIndex = 2;
            layout.Controls.Add(notes, 0, 3);

            var close = new ModernButton { Text = "&Close", AccessibleName = "Close changelog", AutoSize = true,
                MinimumSize = new Size(80, 28), Anchor = AnchorStyles.Right, DialogResult = DialogResult.Cancel,
                TabIndex = 3 };
            layout.Controls.Add(close, 0, 4);
            CancelButton = close;
            versions.Items.AddRange(ReleaseHistory.Releases);
            versions.SelectedIndexChanged += delegate {
                var release = (ReleaseNote)versions.SelectedItem;
                title.Text = release.Title;
                notes.Text = "• " + String.Join(Environment.NewLine + Environment.NewLine + "• ", release.Changes);
                notes.SelectionStart = 0;
                notes.SelectionLength = 0;
                notes.ScrollToCaret();
            };
            versions.SelectedIndex = 0;
            Shown += delegate { versions.Focus(); };
        }

        protected override void Dispose(bool disposing)
        {
            base.Dispose(disposing);
            if (disposing) titleFont.Dispose();
        }
    }
}
