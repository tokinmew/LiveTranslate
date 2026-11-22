using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class PickerSource
    {
        internal string Code, Name, Region, Aliases;
        internal string[] States;
    }

    internal sealed partial class MainForm
    {
        private LanguagePicker activePicker;

        private void SyncLanguageButton()
        {
            if (pickLanguage == null) return;
            Choice choice = profileSelector.SelectedItem as Choice;
            pickLanguage.Text = choice == null ? "Choose language" : choice.Name;
            pickLanguage.AccessibleName = "Choose source language, " + pickLanguage.Text;
        }

        private List<PickerSource> PickerSources()
        {
            List<PickerSource> sources = new List<PickerSource>();
            foreach (Choice choice in profileSelector.Items)
            {
                Dictionary<string, object> info;
                profiles.TryGetValue(choice.Code, out info);
                string region = info == null ? "" : Value(info, "region");
                if (PriorityProfile(choice.Code)) region = "Asia";
                if (choice.Code == "auto") region = "Automatic";
                if (choice.Code == "other") region = "Advanced";
                PickerSource item = new PickerSource { Code = choice.Code, Name = choice.Name,
                    Region = String.IsNullOrEmpty(region) ? "Other" : region, Aliases = "", States = new string[3] };
                if (info != null)
                    item.Aliases = Value(info, "text_language") + " " + Value(info, "speech_language") + " " + Value(info, "ocr_language");
                for (int i = 0; i < item.States.Length; i++) item.States[i] = ModeState(item.Code, info, i);
                sources.Add(item);
            }
            return sources;
        }

        private void OpenLanguagePicker()
        {
            using (LanguagePicker picker = new LanguagePicker())
            {
                activePicker = picker;
                try
                {
                    picker.SetSources(PickerSources(), ProfileCode());
                    if (picker.ShowDialog(this) == DialogResult.OK && picker.ChosenCode != null)
                        SelectProfile(picker.ChosenCode);
                }
                finally { activePicker = null; }
            }
        }
    }

    internal sealed class LanguagePicker : Form
    {
        internal static readonly string[] Modes = { "Text", "Audio", "Screen" };
        private static readonly string[] Regions = { "Automatic", "Asia", "Europe", "Africa", "Americas", "Oceania", "Other", "Advanced" };
        private static readonly string[] Pinned = { "zt", "zh", "ko", "ja" };
        private static readonly Color Ink = Color.FromArgb(32, 38, 60);
        private static readonly Color Quiet = Color.FromArgb(79, 89, 111);
        private static readonly Color Purple = Color.FromArgb(85, 69, 172);
        private readonly TextBox search = new TextBox();
        private readonly ListView results = new ListView();
        private readonly Label resultCount = new Label();
        private readonly Button use = new ModernButton();
        private readonly CompareInfo compare = CultureInfo.InvariantCulture.CompareInfo;
        private List<PickerSource> sources = new List<PickerSource>();
        internal string ChosenCode { get; private set; }

        internal LanguagePicker()
        {
            Text = "Choose source language";
            AccessibleName = Text;
            Font = new Font("Segoe UI", 10F);
            ForeColor = Ink;
            BackColor = Color.FromArgb(248, 248, 253);
            AutoScaleDimensions = new SizeF(96, 96);
            AutoScaleMode = AutoScaleMode.Dpi;
            Size = new Size(665, 600);
            MinimumSize = new Size(455, 365);
            MaximizeBox = false;
            MinimizeBox = false;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;

            TableLayoutPanel page = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 6, Padding = new Padding(20, 12, 20, 16) };
            page.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            foreach (int h in new[] { 44, 24, 36, 0, 28, 39 })
                page.RowStyles.Add(new RowStyle(h == 0 ? SizeType.Percent : SizeType.Absolute, h == 0 ? 100 : h));
            Controls.Add(page);
            page.Controls.Add(new Label { Text = "Choose source language", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
                Font = new Font(Font.FontFamily, 17, FontStyle.Bold), Margin = Padding.Empty }, 0, 0);
            page.Controls.Add(new Label { Text = "Search by language name or code", ForeColor = Quiet, Margin = Padding.Empty, Dock = DockStyle.Fill }, 0, 1);
            search.AccessibleName = "Search languages by name or code";
            search.Dock = DockStyle.Fill;
            search.Margin = Padding.Empty;
            search.TextChanged += delegate { Filter(SelectedCode()); };
            search.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyCode == Keys.Down && results.Items.Count > 0)
                {
                    results.Focus();
                    if (results.SelectedItems.Count == 0) results.Items[0].Selected = true;
                    e.SuppressKeyPress = true;
                }
            };
            page.Controls.Add(search, 0, 2);
            results.View = View.Details;
            results.HeaderStyle = ColumnHeaderStyle.Nonclickable;
            results.AccessibleName = "Languages and available translation inputs";
            results.GridLines = false;
            results.FullRowSelect = true;
            results.MultiSelect = false;
            results.HideSelection = false;
            results.ShowGroups = true;
            results.Dock = DockStyle.Fill;
            results.Margin = Padding.Empty;
            results.Columns.Add("Language");
            foreach (string mode in Modes) results.Columns.Add(mode);
            results.SizeChanged += delegate { FitColumns(); };
            results.SelectedIndexChanged += delegate { use.Enabled = SelectedCode() != null; };
            results.ItemActivate += delegate { Choose(); };
            page.Controls.Add(results, 0, 3);
            resultCount.Dock = DockStyle.Fill;
            resultCount.TextAlign = ContentAlignment.MiddleLeft;
            resultCount.AccessibleRole = AccessibleRole.StatusBar;
            resultCount.Margin = Padding.Empty;
            resultCount.ForeColor = Quiet;
            page.Controls.Add(resultCount, 0, 4);
            FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Fill, Margin = Padding.Empty, FlowDirection = FlowDirection.RightToLeft, WrapContents = false };
            use.Text = "Use language";
            use.BackColor = Purple;
            use.ForeColor = Color.White;
            use.FlatAppearance.BorderColor = Purple;
            use.Size = new Size(137, 34);
            use.Margin = new Padding(8, 4, 0, 0);
            use.Click += delegate { Choose(); };
            actions.Controls.Add(use);
            Button cancel = new ModernButton { Text = "Cancel", DialogResult = DialogResult.Cancel, Size = new Size(84, 34), BackColor = Color.White,
                ForeColor = Ink, Margin = new Padding(0, 4, 0, 0) };
            cancel.FlatAppearance.BorderColor = Color.FromArgb(182, 189, 209);
            actions.Controls.Add(cancel);
            page.Controls.Add(actions, 0, 5);
            CancelButton = cancel;
            AcceptButton = use;
            ActiveControl = search;
            Shown += delegate { FitColumns(); search.Focus(); };
        }

        private void FitColumns()
        {
            int available = Math.Max(1, results.ClientSize.Width - SystemInformation.VerticalScrollBarWidth - 4);
            int stateWidth = Math.Max(1, Math.Min(TextRenderer.MeasureText("Unsupported", results.Font).Width + 9, available / 4));
            for (int index = 1; index <= Modes.Length; index++) results.Columns[index].Width = stateWidth;
            results.Columns[0].Width = Math.Max(1, available - Modes.Length * stateWidth);
        }

        private static int Rank(string[] values, string value)
        {
            int rank = Array.IndexOf(values, value);
            return rank < 0 ? values.Length : rank;
        }

        internal void SetSources(List<PickerSource> items, string selected)
        {
            string previous = SelectedCode();
            sources = new List<PickerSource>(items);
            sources.Sort(delegate(PickerSource a, PickerSource b)
            {
                int region = Rank(Regions, a.Region).CompareTo(Rank(Regions, b.Region));
                if (region != 0) return region;
                int pinned = Rank(Pinned, a.Code).CompareTo(Rank(Pinned, b.Code));
                return pinned != 0 ? pinned : StringComparer.CurrentCultureIgnoreCase.Compare(a.Name, b.Name);
            });
            Filter(previous ?? selected);
        }

        private string SelectedCode()
        {
            return results.SelectedItems.Count == 0 ? null : (string)results.SelectedItems[0].Tag;
        }

        private void Filter(string selected)
        {
            string query = search.Text.Trim();
            results.BeginUpdate();
            ListViewItem selection = null;
            try
            {
                results.Items.Clear();
                results.Groups.Clear();
                Dictionary<string, ListViewGroup> groups = new Dictionary<string, ListViewGroup>();
                foreach (PickerSource source in sources)
                {
                    string terms = source.Name + " " + source.Code + " " + source.Aliases;
                    if (query.Length > 0 && compare.IndexOf(terms, query, CompareOptions.IgnoreCase | CompareOptions.IgnoreNonSpace) < 0) continue;
                    ListViewGroup group;
                    if (!groups.TryGetValue(source.Region, out group))
                    {
                        group = new ListViewGroup(source.Region, HorizontalAlignment.Left);
                        groups[source.Region] = group;
                        results.Groups.Add(group);
                    }
                    ListViewItem item = new ListViewItem(source.Name, group);
                    item.Tag = source.Code;
                    item.SubItems.AddRange(source.States);
                    results.Items.Add(item);
                    if (source.Code == selected) selection = item;
                }
                if (selection == null && results.Items.Count > 0) selection = results.Items[0];
            }
            finally { results.EndUpdate(); }
            if (selection != null)
            {
                selection.Selected = selection.Focused = true;
                selection.EnsureVisible();
            }
            use.Enabled = selection != null;
            int count = results.Items.Count;
            resultCount.Text = count == 0 ? "No matches. Try a different name or code." : count == 1 ? "1 match" : count + " languages";
        }

        private void Choose()
        {
            string code = SelectedCode();
            if (code == null) return;
            ChosenCode = code;
            DialogResult = DialogResult.OK;
        }
    }
}
