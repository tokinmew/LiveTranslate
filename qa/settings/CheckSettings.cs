using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
using LiveTranslate;

internal static class CheckSettings
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static string folder;
    static int passed;
    static T Field<T>(object owner, string name) { return (T)owner.GetType().GetField(name, Private).GetValue(owner); }
    static object Call(object owner, string name, params object[] args) { return owner.GetType().GetMethod(name, Private).Invoke(owner, args); }
    static void Check(bool ok, string text) { if (!ok) throw new InvalidOperationException(text); Console.WriteLine("PASS " + text); passed++; }
    static void Layout(Control control) { IntPtr handle = control.Handle; foreach (Control child in control.Controls) Layout(child); control.PerformLayout(); }
    static void Render(Form form, string name)
    {
        Application.DoEvents(); Layout(form);
        using (Bitmap image = new Bitmap(form.ClientSize.Width, form.ClientSize.Height))
        {
            using (Graphics g = Graphics.FromImage(image)) g.Clear(form.BackColor);
            form.Controls[0].DrawToBitmap(image, new Rectangle(Point.Empty, image.Size));
            image.Save(Path.Combine(folder, name + ".png"), ImageFormat.Png);
        }
    }
    static PickerSource Source(string code, string name, string region, string aliases)
    {
        return new PickerSource { Code = code, Name = name, Region = region, Aliases = aliases, States = new[] {"Ready", "Ready", "Set up"} };
    }
    static string Selected(ListView rows) { return rows.SelectedItems.Count == 1 ? (string)rows.SelectedItems[0].Tag : null; }
    static void Picker()
    {
        using (var picker = new LanguagePicker())
        {
            var choices = new List<PickerSource> {
                Source("auto", "Auto-detect language", "Automatic", ""), Source("zt", "Traditional Chinese  繁體中文", "Asia", "zh chi_tra"),
                Source("zh", "Simplified Chinese  简体中文", "Asia", "zh chi_sim"), Source("ko", "Korean  한국어", "Asia", "kor"),
                Source("ja", "Japanese  日本語", "Asia", "jpn"), Source("de", "German", "Europe", "deu"),
                Source("nb", "Norwegian Bokmål", "Europe", "nob"), Source("sv", "Swedish", "Europe", "swe") };
            picker.SetSources(choices, "ko"); picker.Opacity = 0; picker.Show(); Layout(picker);
            var search = Field<TextBox>(picker, "search"); var rows = Field<ListView>(picker, "results");
            Check(Selected(rows) == "ko", "current Korean source selected on opening");
            Check(rows.Groups[0].Header == "Automatic" && rows.Groups[1].Header == "Asia", "automatic and Asian sources shown first when browsing");
            Render(picker, "source-language");
            search.Text = "de"; Check(Selected(rows) == "de", "exact language code beats partial or automatic-mode matches");
            search.Text = "zh"; Check(Selected(rows) == "zh", "exact Chinese code outranks a shared speech alias");
            search.Text = "chi_tra"; Check(Selected(rows) == "zt", "OCR alias finds Traditional Chinese");
            search.Text = "bokmal europe"; Check(Selected(rows) == "nb", "region and accent-insensitive words can be combined");
            search.Text = "한국"; Check(Selected(rows) == "ko", "native-script Korean search");
            search.Text = "日本"; Check(Selected(rows) == "ja", "native-script Japanese search");
            search.Text = "europe"; Check(rows.Items.Count == 3, "regional filter");
            rows.Items[2].Selected = true; string before = Selected(rows); var existing = rows.Items[2]; picker.SetSources(choices, "ko");
            Check(before == Selected(rows) && Object.ReferenceEquals(existing, rows.Items[2]), "unchanged metadata preserves the list, selection and scroll");
            var changed = new List<PickerSource>(choices);
            changed[changed.Count - 1] = Source("sv", "Swedish", "Europe", "swe"); changed[changed.Count - 1].States[0] = "Set up";
            picker.SetSources(changed,"ko"); Check(before == Selected(rows) && rows.Items[2].SubItems[1].Text == "Set up", "new availability updates while preserving user's selection");
            search.Text = "zzzzzz"; Check(rows.Items.Count == 0 && !Field<Button>(picker,"use").Enabled, "no-match action disabled");
            Message message = new Message(); Call(picker, "ProcessCmdKey", message, Keys.Escape);
            Check(search.Text == "" && Selected(rows) == "ko", "Escape clears the filter and restores active language");
            Call(picker, "ProcessCmdKey", message, Keys.Control | Keys.F); Check(search.Focused, "Control F focuses search");
            search.Text = "de";
            var down = new KeyEventArgs(Keys.Down); Call(search, "OnKeyDown", down);
            Check(rows.Focused && down.SuppressKeyPress, "Down moves keyboard focus from the query to results");
            Call(picker, "ProcessCmdKey", message, Keys.Control | Keys.F);
            Call(picker, "ProcessDialogKey", Keys.Enter);
            Check(picker.ChosenCode == "de" && picker.DialogResult == DialogResult.OK, "native dialog Enter commits the selected result from search");
        }
    }

    static void Settings()
    {
        using (var app = new MainForm())
        using (var form = Field<Form>(app, "settingsForm"))
        {
            var tabs = Field<TabControl>(app, "settingsTabs");
            form.Opacity = 0; form.Show(); Layout(form);
            Check(tabs.TabCount == 4, "all four settings sections available");
            string[] files = { "recognition", "language-files", "updates", "voice" };
            for (int i=0;i<tabs.TabCount;i++)
            {
                tabs.SelectedIndex=i; Application.DoEvents();
                if (i == 2) Call(app, "SetReleaseSource", "https://github.com/tokinmew/LiveTranslate", false);
                if (i == 3)
                {
                    foreach (string name in new[] { "spokenVoice", "spokenDevice" })
                    {
                        var combo = Field<ComboBox>(app, name); combo.Items.Clear(); combo.Items.Add(name == "spokenVoice" ? "First installed English voice" : "Windows default playback"); combo.SelectedIndex = 0;
                    }
                    Field<Label>(app, "voiceStatus").Text = "Changes take effect immediately. Turn reading off to stop the voice and clear queued translations.";
                }
                Render(form, files[i]);
                Check(!tabs.SelectedTab.HorizontalScroll.Visible, "no horizontal scroll at normal size: " + files[i]);
            }
            form.Size=form.MinimumSize;
            for (int i=0;i<tabs.TabCount;i++)
            {
                tabs.SelectedIndex=i; Application.DoEvents(); Layout(form);
                Check(!tabs.SelectedTab.HorizontalScroll.Visible, "no horizontal scroll at minimum size: " + files[i]);
                Check(!tabs.SelectedTab.VerticalScroll.Visible || tabs.SelectedTab.VerticalScroll.Maximum > tabs.SelectedTab.ClientSize.Height, "scrollable content remains reachable: " + files[i]);
            }
            tabs.SelectedIndex=1; Render(form,"compact-files");
            Check(Field<NumericUpDown>(app, "threads").AccessibleName.Length > 0 && Field<ComboBox>(app, "spokenVoice").AccessibleName.Length > 0, "processing and voice inputs named for screen readers");
            tabs.SelectedIndex=2;
            var download = Field<Button>(app,"installUpdate");
            Check(!download.Visible, "download action hidden until an update is available");
            app.GetType().GetField("offeredVersion",Private).SetValue(app,"0.6.7");
            app.GetType().GetField("offeredDigest",Private).SetValue(app,new string('a',64));
            Call(app,"RefreshUpdateActions"); Check(download.Visible && download.Enabled,"a release offer exposes the download action");
            using (var job = new System.Threading.CancellationTokenSource())
            {
                app.GetType().GetField("updateJob",Private).SetValue(app,job); Call(app,"RefreshUpdateActions");
                var cancel = Field<Button>(app,"cancelUpdate");
                Check(cancel.Visible && !Field<TextBox>(app,"updateSource").Enabled && Field<ProgressBar>(app,"updateActivity").Visible,"checking a source locks its address and shows cancellation and activity");
                cancel.PerformClick(); Check(job.IsCancellationRequested,"Cancel signals the active update job");
                app.GetType().GetField("updateJob",Private).SetValue(app,null); Call(app,"RefreshUpdateActions");
            }
            Field<TextBox>(app,"updateSource").Text="";
            Check(!download.Visible && !Field<ProgressBar>(app,"updateActivity").Visible,"editing the feed invalidates its offer and clears activity");
            Call(app,"RememberProcessingSettings");
            app.GetType().GetField("screenSession", Private).SetValue(app,"untouched-fixture");
            Call(form,"ProcessDialogKey", Keys.Escape);
            Check(Field<string>(app,"screenSession") == "untouched-fixture" && !form.Visible,"closing unchanged settings keeps capture session unchanged");
            Call(app,"SelectProfile","other");
            form.Show(); Call(app,"RememberProcessingSettings");
            Field<TextBox>(app,"audioLanguage").Text = "de"; Field<TextBox>(app,"ocrLanguage").Text = "deu";
            var fake = new Dictionary<string,object> { {"type","status"}, {"installed_languages",new object[0]}, {"profiles",new object[0]} };
            Call(app,"HandleMessage",fake);
            Check(Field<TextBox>(app,"audioLanguage").Text == "de" && Field<TextBox>(app,"ocrLanguage").Text == "deu", "status refresh preserves custom recognition edits");
            tabs.SelectedTab=Field<TabPage>(app,"spokenTab"); Call(app,"ApplySettings");
            Check(Field<Dictionary<string,string>>(app,"speechOverrides")["other"] == "de" && Field<Dictionary<string,string>>(app,"ocrOverrides")["other"] == "deu", "pending custom recognition settings apply from spoken tab");
            Check(Field<System.Diagnostics.Process>(app,"worker") == null, "no worker or capture device started");
        }
    }

    static void ScaledLayout(float scale)
    {
        using (var app = new MainForm())
        using (var settings = Field<Form>(app, "settingsForm"))
        using (var picker = new LanguagePicker())
        {
            var tabs = Field<TabControl>(app, "settingsTabs");
            settings.Opacity = 0; settings.Show();
            settings.Size = settings.MinimumSize;
            settings.Scale(new SizeF(scale, scale));
            for (int i = 0; i < tabs.TabCount; i++)
            {
                tabs.SelectedIndex = i; Application.DoEvents(); Layout(settings);
                Check(!tabs.SelectedTab.HorizontalScroll.Visible && tabs.SelectedTab.Width <= settings.ClientSize.Width,
                    "compact settings geometry scaled " + scale + "x, tab " + i);
                var footer = ((Control)settings.CancelButton).RectangleToScreen(((Control)settings.CancelButton).ClientRectangle);
                Check(settings.RectangleToScreen(settings.ClientRectangle).Contains(footer), "Done stays within scaled window, tab " + i);
            }
            picker.Opacity = 0; picker.Show(); picker.Size = picker.MinimumSize; picker.Scale(new SizeF(scale, scale)); Layout(picker);
            var list = Field<ListView>(picker, "results"); var apply = Field<Button>(picker, "use");
            int columns = 0; foreach (ColumnHeader column in list.Columns) columns += column.Width;
            Check(columns <= list.ClientSize.Width && apply.ClientSize.Height >= 28 && list.Height > 45, "compact picker remains operable at simulated " + scale + "x");
        }
    }
    [STAThread] static void Main(string[] args)
    {
        folder=args[0]; Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        Picker(); Settings(); foreach (float factor in new[] { 1.25f, 1.5f, 2f }) ScaledLayout(factor);
        Console.WriteLine(passed + " settings and picker checks passed.");
    }
}
