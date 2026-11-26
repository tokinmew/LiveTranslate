using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using LiveTranslate;

// Authored, offscreen app fixtures. No worker, microphone or personal screen is opened.
internal static class QuietThemeCheck
{
    const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;
    [DllImport("user32.dll", SetLastError = true)] static extern bool PrintWindow(IntPtr window, IntPtr device, uint flags);
    static int passed;
    static T Field<T>(MainForm app, string name) { return (T)typeof(MainForm).GetField(name, Instance).GetValue(app); }
    static void Put(MainForm app, string name, object value) { typeof(MainForm).GetField(name, Instance).SetValue(app, value); }
    static void Call(MainForm app, string name, params object[] args) { typeof(MainForm).GetMethod(name, Instance).Invoke(app, args); }
    static void Check(bool condition, string detail)
    {
        if (!condition) throw new InvalidOperationException(detail);
        Console.WriteLine("PASS " + detail); passed++;
    }
    static void RemoveEvent(Form window, string name)
    {
        EventHandlerList events = (EventHandlerList)typeof(Component).GetProperty("Events", Instance).GetValue(window, null);
        object key = typeof(Form).GetField(name, Static).GetValue(null);
        if (events[key] != null) events.RemoveHandler(key, events[key]);
    }
    static void OutsideDisplays(Form window)
    {
        window.ShowInTaskbar = false;
        window.StartPosition = FormStartPosition.Manual;
        window.Location = new Point(SystemInformation.VirtualScreen.Right + 200, 0);
    }
    static Bitmap Render(Control control)
    {
        control.PerformLayout(); Application.DoEvents(); control.Update();
        Bitmap image = new Bitmap(control.Width, control.Height);
        using (Graphics graphics = Graphics.FromImage(image))
        {
            IntPtr device = graphics.GetHdc();
            try { if (!PrintWindow(control.Handle, device, 2)) throw new Win32Exception(Marshal.GetLastWin32Error()); }
            finally { graphics.ReleaseHdc(device); }
        }
        return image;
    }
    static void Save(Control control, string path) { using (Bitmap image = Render(control)) image.Save(path, ImageFormat.Png); }
    static bool Dark(Color value) { return value.R < 150 && value.G < 150 && value.B < 150; }
    static void DarkFace(Control control, string description)
    {
        using (Bitmap image = Render(control))
        {
            int y = Math.Max(1, image.Height - 4);
            Check(Dark(image.GetPixel(image.Width / 2, y)) && Dark(image.GetPixel(image.Width - 5, y)), description);
        }
    }
    static CheckBox FindCheck(Control parent, string text)
    {
        CheckBox checkbox = parent as CheckBox;
        if (checkbox != null && checkbox.Text == text) return checkbox;
        foreach (Control child in parent.Controls)
        {
            CheckBox found = FindCheck(child, text);
            if (found != null) return found;
        }
        return null;
    }
    static void FullCheckbox(CheckBox checkbox, string description)
    {
        Check(checkbox != null && checkbox.Visible, description + " remains visible");
        Size words = TextRenderer.MeasureText(checkbox.Text, checkbox.Font);
        float scale;
        using (Graphics graphics = checkbox.CreateGraphics()) scale = graphics.DpiX / 96F;
        int needed = words.Width + (int)Math.Ceiling(23 * scale);
        Check(checkbox.Width >= needed && checkbox.GetPreferredSize(Size.Empty).Width >= needed,
            description + " reserves room for the complete label and custom checkbox");
    }
    static void DarkTabs(TabControl tabs)
    {
        using (Bitmap image = Render(tabs))
        {
            Check(Dark(image.GetPixel(0, image.Height / 2)) && Dark(image.GetPixel(image.Width - 1, image.Height - 2)),
                "Settings page frame contains no bright native outline");
            bool dark = true;
            for (int i = 0; i < tabs.TabCount; i++)
            {
                Rectangle tab = tabs.GetTabRect(i);
                dark &= Dark(image.GetPixel(Math.Min(image.Width - 1, tab.Right - 2), tab.Top + 1));
            }
            Check(dark, "Selected and unselected native tab header faces remain dark");
        }
    }
    static void NumericChrome(NumericUpDown number, string description)
    {
        Control buttons = null;
        foreach (Control child in number.Controls) if (child.GetType().Name == "UpDownButtons") buttons = child;
        Check(buttons != null, description + " keeps the native repeat buttons");
        using (Bitmap image = Render(buttons))
            Check(Dark(image.GetPixel(1, 1)) && Dark(image.GetPixel(image.Width - 2, image.Height - 2)),
                description + " paints both spinner-button backgrounds in the dark theme");
    }
    [STAThread] static int Main(string[] args)
    {
        string directory = Path.GetFullPath(args[0]);
        Directory.CreateDirectory(directory);
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        using (MainForm app = new MainForm())
        {
            RemoveEvent(app, "EVENT_LOAD"); RemoveEvent(app, "EVENT_SHOWN");
            OutsideDisplays(app); app.Size = new Size(1280, 820); app.Show();
            Put(app, "screenArmed", false); Put(app, "connected", true); Put(app, "devicesReady", true);
            ComboBox devices = Field<ComboBox>(app, "devices");
            devices.Items.Add(new Choice("pc", "Computer audio · Default playback and calls") { DeviceId = -2 });
            devices.Items.Add(new Choice("microphone", "Microphone · Fixture input") { DeviceId = 7 });
            devices.SelectedIndex = 0;
            Call(app, "UpdateControls"); app.ShowSessionPage("audio");
            Field<Label>(app, "audioStateLabel").Text = "Off. Choose computer audio for games, videos and voice chat.";
            Call(app, "SetStatus", "Local engine ready.");
            Check(devices.Visible && devices.Enabled && devices.SelectedIndex == 0,
                "Audio setup renders the actual enabled selected playback dropdown");
            DarkFace(devices, "Actual enabled audio dropdown has a dark closed face and arrow background");
            Save(app, Path.Combine(directory, "quiet-audio-setup.png"));
            devices.SelectedIndex = 1;
            Check(Field<Label>(app, "sessionAudioSourceTitle").Text == "Microphone" && !Field<bool>(app, "audioWanted"),
                "Themed audio selector keeps stopped source-selection behavior");
            devices.SelectedIndex = 0;
            Form settings = Field<Form>(app, "settingsForm");
            RemoveEvent(settings, "EVENT_LOAD"); OutsideDisplays(settings);
            Call(app, "OpenSettings");
            TabControl tabs = Field<TabControl>(app, "settingsTabs");
            tabs.SelectedIndex = 0; Application.DoEvents();
            DarkTabs(tabs);
            ComboBox disabled = Field<ComboBox>(app, "customTextSource");
            Check(!disabled.Enabled, "Unavailable custom source stays disabled");
            DarkFace(disabled, "Actual disabled source dropdown retains a dark face");
            NumericUpDown chunks = Field<NumericUpDown>(app, "chunks");
            NumericUpDown threads = Field<NumericUpDown>(app, "threads");
            decimal chunkValue = chunks.Value, threadValue = threads.Value;
            NumericChrome(chunks, "Phrase duration"); NumericChrome(threads, "CPU threads");
            using (Bitmap image = Render(Field<TextBox>(app, "audioLanguage")))
                Check(Dark(image.GetPixel(0, image.Height / 2)) && Dark(image.GetPixel(image.Width - 1, image.Height / 2)),
                    "Read-only language-code field has quiet native edges");
            FullCheckbox(FindCheck(settings, "Keep the dashboard on top"), "Dashboard pin preference");
            Save(settings, Path.Combine(directory, "quiet-settings.png"));
            MethodInfo key = typeof(TabControl).GetMethod("ProcessCmdKey", Instance);
            for (int index = 1; index <= tabs.TabCount; index++)
            {
                tabs.Focus();
                Message message = Message.Create(tabs.Handle, 0x100, new IntPtr((int)Keys.Tab), IntPtr.Zero);
                object[] parameters = { message, Keys.Control | Keys.Tab };
                key.Invoke(tabs, parameters); Application.DoEvents();
                Check(tabs.SelectedIndex == index % tabs.TabCount, "Control+Tab selects the expected settings section " + (index % tabs.TabCount));
            }
            tabs.SelectedIndex = 3; Application.DoEvents();
            FullCheckbox(FindCheck(settings, "Read voice translations aloud"), "Spoken English preference");
            Save(settings, Path.Combine(directory, "quiet-spoken-settings.png"));
            Check(chunks.Value == chunkValue && threads.Value == threadValue && devices.SelectedIndex == 0,
                "Changing themed sections preserves recognition values and selected audio device");
            Check(Field<object>(app, "worker") == null && !Field<bool>(app, "audioWanted") && !Field<bool>(app, "screenWanted"),
                "Complete theme fixture starts no worker, audio stream or screen capture");
            settings.Hide(); app.Hide();
        }
        Console.WriteLine(passed + " integrated quiet-theme checks passed; isolated app fixtures only.");
        return 0;
    }
}
