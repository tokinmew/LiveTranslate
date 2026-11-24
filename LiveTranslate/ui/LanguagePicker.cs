using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Runtime.InteropServices;
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
        private static Color Ink { get { return WindowTheme.Ink; } }
        private static Color Quiet { get { return WindowTheme.Muted; } }
        private static Color Primary { get { return WindowTheme.Accent; } }
        private readonly TextBox search = new ThemedTextBox();
        private readonly ListView results = new LanguageResults();
        private readonly Label resultCount = new Label();
        private readonly Button use = new ModernButton();
        private static readonly CompareInfo Compare = CultureInfo.InvariantCulture.CompareInfo;
        private const CompareOptions SearchOptions = CompareOptions.IgnoreCase | CompareOptions.IgnoreNonSpace;
        private List<PickerSource> sources = new List<PickerSource>();
        private string currentCode;
        internal string ChosenCode { get; private set; }

        private sealed class LanguageResults : ListView
        {
            [StructLayout(LayoutKind.Sequential)] private struct Header { internal IntPtr Window, Id; internal int Code; }
            [StructLayout(LayoutKind.Sequential)] private struct NativeRect { internal int Left, Top, Right, Bottom; }
            [StructLayout(LayoutKind.Sequential)] private struct CustomDraw
            {
                internal Header Header; internal int Stage; internal IntPtr Device;
                internal NativeRect Bounds; internal IntPtr Item; internal uint State; internal IntPtr Data;
            }
            [StructLayout(LayoutKind.Sequential)] private struct ListDraw
            {
                internal CustomDraw Draw; internal uint Text, TextBack; internal int Subitem;
                internal uint ItemType, Face; internal int IconEffect, IconPhase, Part, State;
                internal NativeRect TextBounds; internal uint Align;
            }
            [StructLayout(LayoutKind.Sequential)] private struct NativeGroup
            {
                internal uint Size, Mask; internal IntPtr Header; internal int HeaderLength;
                internal IntPtr Footer; internal int FooterLength, Id; internal uint StateMask, State, Align;
            }
            [DllImport("user32.dll", CharSet=CharSet.Unicode)]
            private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, ref NativeGroup group);
            private string GroupTitle(IntPtr id)
            {
                IntPtr buffer = Marshal.AllocHGlobal(1024);
                try
                {
                    Marshal.Copy(new byte[1024],0,buffer,1024);
                    NativeGroup group = new NativeGroup { Size=(uint)Marshal.SizeOf(typeof(NativeGroup)), Mask=1, Header=buffer, HeaderLength=512 };
                    if (SendMessage(Handle,0x1095,id,ref group).ToInt64() == -1) return ""; // LVM_GETGROUPINFO
                    return Marshal.PtrToStringUni(buffer) ?? "";
                }
                finally { Marshal.FreeHGlobal(buffer); }
            }
            protected override void WndProc(ref Message message)
            {
                if (!WindowTheme.HighContrast && (message.Msg == 0x004E || message.Msg == 0x204E) && message.LParam != IntPtr.Zero)
                {
                    Header header = (Header)Marshal.PtrToStructure(message.LParam,typeof(Header));
                    if (header.Code == -12) // NM_CUSTOMDRAW, native list/header notifications.
                    {
                        CustomDraw draw = (CustomDraw)Marshal.PtrToStructure(message.LParam,typeof(CustomDraw));
                        if (message.Msg == 0x004E)
                        {
                            if (draw.Stage == 1) { message.Result = new IntPtr(0x30); return; }
                            if (draw.Stage == 2)
                            {
                                int used = 0; foreach (ColumnHeader item in Columns) used += item.Width;
                                if (used < ClientSize.Width)
                                    using (Graphics graphics = Graphics.FromHdc(draw.Device))
                                    using (Brush fill = new SolidBrush(WindowTheme.Field))
                                        graphics.FillRectangle(fill,used,draw.Bounds.Top,ClientSize.Width-used,draw.Bounds.Bottom-draw.Bounds.Top);
                                message.Result = IntPtr.Zero; return;
                            }
                            int column = draw.Item.ToInt32();
                            if (draw.Stage == 0x10001 && column >= 0 && column < Columns.Count)
                            {
                                Rectangle area = Rectangle.FromLTRB(draw.Bounds.Left,draw.Bounds.Top,draw.Bounds.Right,draw.Bounds.Bottom);
                                if (column == Columns.Count-1) area.Width = Math.Max(area.Width,ClientSize.Width-area.Left);
                                using (Graphics graphics = Graphics.FromHdc(draw.Device))
                                using (Brush fill = new SolidBrush(WindowTheme.Field))
                                using (Pen edge = new Pen(WindowTheme.Border))
                                {
                                    graphics.FillRectangle(fill,area);
                                    graphics.DrawLine(edge,area.Right-1,area.Top,area.Right-1,area.Bottom);
                                    area.Inflate(-7,0);
                                    TextRenderer.DrawText(graphics,Columns[column].Text,Font,area,WindowTheme.Muted,
                                        TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis);
                                }
                                message.Result = new IntPtr(4); return; // CDRF_SKIPDEFAULT
                            }
                        }
                        else
                        {
                            base.WndProc(ref message);
                            ListDraw list = (ListDraw)Marshal.PtrToStructure(message.LParam,typeof(ListDraw));
                            if (draw.Stage == 1) message.Result = new IntPtr(message.Result.ToInt64() | (list.ItemType == 1 ? 0x10L : 0x20L));
                            else if (draw.Stage == 2)
                            {
                                if (list.ItemType == 1) // LVCDI_GROUP. Keep native layout/selection.
                                {
                                    Rectangle area = Rectangle.FromLTRB(list.TextBounds.Left,list.TextBounds.Top,list.TextBounds.Right,list.TextBounds.Bottom);
                                    if (area.Width > 0 && area.Height > 0)
                                    {
                                        using (Graphics graphics = Graphics.FromHdc(draw.Device))
                                        using (Brush fill = new SolidBrush(WindowTheme.Card))
                                        {
                                            graphics.FillRectangle(fill,area);
                                            TextRenderer.DrawText(graphics,GroupTitle(draw.Item),Font,area,WindowTheme.Muted,
                                                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis);
                                        }
                                        message.Result = IntPtr.Zero;
                                    }
                                }
                            }
                            return;
                        }
                    }
                }
                base.WndProc(ref message);
            }
        }

        internal LanguagePicker()
        {
            Text = "Choose source language";
            AccessibleName = Text;
            Font = new Font("Segoe UI", 10F);
            ForeColor = Ink;
            BackColor = WindowTheme.Background;
            WindowTheme.Apply(this);
            AutoScaleDimensions = new SizeF(96, 96);
            AutoScaleMode = AutoScaleMode.Dpi;
            Size = new Size(680, 616);
            MinimumSize = new Size(455, 365);
            MaximizeBox = false;
            MinimizeBox = false;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;

            TableLayoutPanel page = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 6, Padding = new Padding(20, 12, 20, 16) };
            page.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            foreach (int h in new[] { 44, 24, 42, 0, 32, 40 })
                page.RowStyles.Add(new RowStyle(h == 0 ? SizeType.Percent : SizeType.Absolute, h == 0 ? 100 : h));
            Controls.Add(page);
            page.Controls.Add(new Label { Text = "Source language", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
                Font = new Font(Font.FontFamily, 17, FontStyle.Bold), Margin = Padding.Empty }, 0, 0);
            page.Controls.Add(new Label { Text = "Search by name, region or language code", ForeColor = Quiet, Margin = Padding.Empty, Dock = DockStyle.Fill }, 0, 1);
            search.AccessibleName = "Search by name, region or language code";
            search.AccessibleDescription = "Use Down to move to the results. Control F returns to search.";
            search.Dock = DockStyle.Top;
            search.Margin = Padding.Empty;
            search.BackColor = WindowTheme.Field;
            search.ForeColor = Ink;
            search.HandleCreated += delegate { WindowTheme.ApplyControl(search); };
            search.TextChanged += delegate { Filter(search.Text.Trim().Length == 0 ? currentCode : null); };
            search.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyCode == Keys.Down && results.Items.Count > 0)
                {
                    results.Focus();
                    if (results.SelectedItems.Count == 0) results.Items[0].Selected = true;
                    e.SuppressKeyPress = true;
                }
            };
            var searchRow = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1, Margin = Padding.Empty };
            searchRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            searchRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 63));
            searchRow.Controls.Add(search, 0, 0);
            var clear = new ModernButton { Text = "Clear", AccessibleName = "Clear language search", Dock = DockStyle.Top,
                Height = 28, Margin = new Padding(6, 0, 0, 0), Enabled = false };
            clear.Click += delegate { search.Clear(); search.Focus(); };
            search.TextChanged += delegate { clear.Enabled = search.Text.Length != 0; };
            searchRow.Controls.Add(clear, 1, 0);
            page.Controls.Add(searchRow, 0, 2);
            results.View = View.Details;
            results.BackColor = WindowTheme.Card;
            results.ForeColor = Ink;
            results.BorderStyle = BorderStyle.FixedSingle;
            results.HandleCreated += delegate { WindowTheme.ApplyControl(results); };
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
            use.BackColor = Primary;
            use.ForeColor = WindowTheme.AccentInk;
            use.FlatAppearance.BorderColor = Primary;
            use.Size = new Size(137, 34);
            use.Margin = new Padding(8, 4, 0, 0);
            use.Click += delegate { Choose(); };
            actions.Controls.Add(use);
            Button cancel = new ModernButton { Text = "Cancel", DialogResult = DialogResult.Cancel, Size = new Size(84, 34), BackColor = WindowTheme.Field,
                ForeColor = Ink, Margin = new Padding(0, 4, 0, 0) };
            cancel.FlatAppearance.BorderColor = WindowTheme.Border;
            actions.Controls.Add(cancel);
            page.Controls.Add(actions, 0, 5);
            CancelButton = cancel;
            AcceptButton = use;
            ActiveControl = search;
            Shown += delegate { FitColumns(); search.Focus(); };
        }

        private void FitColumns()
        {
            if (results.Columns.Count != Modes.Length + 1) return;
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
            var next = new List<PickerSource>(items);
            next.Sort(delegate(PickerSource a, PickerSource b)
            {
                int region = Rank(Regions, a.Region).CompareTo(Rank(Regions, b.Region));
                if (region != 0) return region;
                int pinned = Rank(Pinned, a.Code).CompareTo(Rank(Pinned, b.Code));
                return pinned != 0 ? pinned : StringComparer.CurrentCultureIgnoreCase.Compare(a.Name, b.Name);
            });
            // Routine status reports often repeat the whole catalogue. Keep the user's scroll and keyboard focus.
            bool changed = currentCode != selected || next.Count != sources.Count;
            for (int i = 0; !changed && i < next.Count; i++)
            {
                PickerSource a = sources[i], b = next[i];
                changed = a.Code != b.Code || a.Name != b.Name || a.Region != b.Region || a.Aliases != b.Aliases ||
                    !System.Linq.Enumerable.SequenceEqual(a.States, b.States);
            }
            if (!changed) return;
            currentCode = selected;
            sources = next;
            Filter(previous ?? selected);
        }

        private string SelectedCode()
        {
            return results.SelectedItems.Count == 0 ? null : (string)results.SelectedItems[0].Tag;
        }

        protected override bool ProcessCmdKey(ref Message message, Keys keys)
        {
            if (keys == (Keys.Control | Keys.F)) { search.Focus(); search.SelectAll(); return true; }
            if (keys == Keys.Escape && search.Text.Length > 0) { search.Clear(); search.Focus(); return true; }
            return base.ProcessCmdKey(ref message, keys);
        }

        private static int MatchRank(PickerSource source, string query, string[] words)
        {
            if (Compare.Compare(source.Code, query, SearchOptions) == 0 || Compare.Compare(source.Name, query, SearchOptions) == 0) return 0;
            string[] aliases = (source.Aliases ?? "").Split(new[] { ' ', '+', ',' }, StringSplitOptions.RemoveEmptyEntries);
            foreach (string alias in aliases) if (Compare.Compare(alias, query, SearchOptions) == 0) return 1;
            if (Compare.IsPrefix(source.Name, query, SearchOptions)) return 2;
            string terms = source.Name + " " + source.Code + " " + source.Region + " " + source.Aliases;
            foreach (string word in words) if (Compare.IndexOf(terms, word, SearchOptions) < 0) return -1;
            return 3;
        }

        private void Filter(string selected)
        {
            string query = search.Text.Trim();
            bool browsing = query.Length == 0;
            List<PickerSource> shown = sources;
            if (!browsing)
            {
                var buckets = new[] { new List<PickerSource>(), new List<PickerSource>(), new List<PickerSource>(), new List<PickerSource>() };
                string[] words = query.Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
                foreach (PickerSource source in sources)
                {
                    int rank = MatchRank(source, query, words);
                    if (rank >= 0) buckets[rank].Add(source);
                }
                shown = new List<PickerSource>();
                foreach (List<PickerSource> bucket in buckets) shown.AddRange(bucket);
            }
            results.BeginUpdate();
            ListViewItem selection = null;
            try
            {
                results.Items.Clear();
                results.Groups.Clear();
                results.ShowGroups = browsing;
                Dictionary<string, ListViewGroup> groups = new Dictionary<string, ListViewGroup>();
                foreach (PickerSource source in shown)
                {
                    ListViewGroup group = null;
                    if (browsing && !groups.TryGetValue(source.Region, out group))
                    {
                        group = new ListViewGroup(source.Region, HorizontalAlignment.Left);
                        groups[source.Region] = group;
                        results.Groups.Add(group);
                    }
                    ListViewItem item = new ListViewItem(source.Name);
                    if (group != null) item.Group = group;
                    item.Tag = source.Code;
                    item.UseItemStyleForSubItems = false;
                    foreach (string state in source.States)
                    {
                        var cell = item.SubItems.Add(state);
                        if (!SystemInformation.HighContrast)
                            cell.ForeColor = state == "Ready" ? Primary : state == "Set up" ? WindowTheme.Warning : Quiet;
                    }
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
            resultCount.Text = count == 0 ? "No matches. Try another name, region or code." : count + (browsing ? " language choices" : count == 1 ? " match" : " matches");
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
