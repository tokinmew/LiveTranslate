using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using LiveTranslate;

internal static class DashboardCheck
{
    const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;
    [DllImport("user32.dll", SetLastError=true)] static extern bool PrintWindow(IntPtr window, IntPtr device, uint flags);
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wp, IntPtr lp);
    static string destination;
    static int passed;
    static T Field<T>(MainForm app, string name) { return (T)typeof(MainForm).GetField(name,Instance).GetValue(app); }
    static void Put(MainForm app, string name, object value) { typeof(MainForm).GetField(name,Instance).SetValue(app,value); }
    static void Run(MainForm app, string name, params object[] args) { typeof(MainForm).GetMethod(name,Instance).Invoke(app,args); }
    static void Check(bool result, string label)
    {
        if (!result) throw new InvalidOperationException(label);
        passed++;
        Console.WriteLine("PASS " + label);
    }
    static void DisconnectStartup(MainForm app)
    {
        EventHandlerList events = (EventHandlerList)typeof(Component).GetProperty("Events",Instance).GetValue(app,null);
        foreach (string name in new[]{"EVENT_LOAD","EVENT_SHOWN"})
        {
            object key = typeof(Form).GetField(name,Static).GetValue(null);
            if (events[key] == null) throw new Exception("Cannot isolate startup handler " + name);
            events.RemoveHandler(key,events[key]);
        }
    }
    static void Snapshot(MainForm app, string name)
    {
        app.PerformLayout();
        Application.DoEvents();
        app.Update();
        using (Bitmap window = new Bitmap(app.ClientSize.Width, app.ClientSize.Height))
        {
            using (Graphics graphics = Graphics.FromImage(window))
            {
                IntPtr dc = graphics.GetHdc();
                try { if (!PrintWindow(app.Handle,dc,3)) throw new Win32Exception(Marshal.GetLastWin32Error()); }
                finally { graphics.ReleaseHdc(dc); }
            }
            window.Save(Path.Combine(destination,name + ".png"),ImageFormat.Png);
        }
    }
    static void AddFixtures(MainForm app)
    {
        var profiles = Field<Dictionary<string, Dictionary<string,object>>>(app,"profiles");
        foreach (string language in new[]{"ja","zh","ko","zt"})
        {
            var entry = new Dictionary<string,object>();
            entry["name"] = language;
            entry["region"] = "Asia";
            foreach(string mode in new[]{"text","screen","speech"}) entry[mode+"_ready"] = entry[mode+"_supported"] = true;
            profiles[language] = entry;
        }
        Put(app,"screenArmed",false);
        Put(app,"connected",true);
        if (typeof(MainForm).GetField("devicesReady",Instance) != null) Put(app,"devicesReady",true);
        ComboBox devices = Field<ComboBox>(app,"devices");
        devices.Items.Add(new Choice("pc", "Computer audio · Default playback"));
        devices.SelectedIndex = 0;
        Run(app,"FillProfiles");
        Run(app,"ApplyProfile",false);
        Field<Label>(app,"audioStateLabel").Text = "Off. Choose a source and turn on Auto listen.";
        Field<Label>(app,"screenStateLabel").Text = "Paused. Read once scans a single frame.";
        Run(app,"SetStatus","Local engine ready.");
        Run(app,"AddCaption","SCREEN","The next train leaves at six.","次の電車は六時に出発します。");
        Run(app,"AddCaption","AUDIO","Shall we go together?","같이 갈까요?");
        Run(app,"AddCaption","SCREEN","Please meet at the east entrance.","請在東門集合。");
    }
    static void CheckTypedRequests(MainForm app)
    {
        TextBox text = Field<TextBox>(app,"input");
        Button action = Field<Button>(app,"translateButton");
        var requests = Field<Dictionary<int,PendingRequest>>(app,"pending");
        using (var stream = new MemoryStream())
        using (var sink = new StreamWriter(stream))
        using (var sentinel = Process.GetCurrentProcess())
        {
            // Exercise production serialization and receipt handling against memory only.
            Put(app,"worker",sentinel); Put(app,"inputWriter",sink);
            try
            {
                text.Text = "  同じ文章  ";
                Run(app,"TranslateInput"); Run(app,"TranslateInput");
                Check(requests.Values.Count(x => x.Command == "translate") == 1 && !action.Enabled,"rapid repeat sends one request for the same text and source");
                int first = Field<int>(app,"requestId");
                Run(app,"SelectProfile","ja");
                Check(action.Enabled,"the same wording can be requested for a different source language");
                Run(app,"TranslateInput");
                int japanese = Field<int>(app,"requestId");
                Run(app,"HandleMessage",new Dictionary<string,object>{{"id",japanese},{"type","result"},{"ignored",true}});
                Run(app,"SelectProfile","auto");
                Check(!action.Enabled,"switching back restores the original in-flight state");
                text.Text = "違う文章";
                Check(action.Enabled,"editing the input permits another translation");
                Run(app,"TranslateInput");
                int second = Field<int>(app,"requestId");
                text.Text = "同じ文章";
                Check(!action.Enabled && requests.Values.Count(x => x.Command == "translate") == 2,"returning to pending wording keeps the duplicate blocked");
                Run(app,"HandleMessage",new Dictionary<string,object>{{"id",second},{"type","error"},{"message","Generated translation error."}});
                Check(!action.Enabled,"another request's failure leaves the first request pending");
                Run(app,"HandleMessage",new Dictionary<string,object>{{"id",first},{"type","result"},{"ignored",true}});
                Check(action.Enabled && !requests.Values.Any(x => x.Command == "translate"),"completed or ignored requests can be retried");
                text.Text = "違う文章";
                Check(action.Enabled,"failed requests can be retried");
            }
            finally { Put(app,"worker",null); Put(app,"inputWriter",null); }
        }
    }
    [STAThread] static void Main(string[] args)
    {
        destination = args[0];
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        using (MainForm app = new MainForm())
        {
            DisconnectStartup(app);
            app.ShowInTaskbar = false;
            // PrintWindow asks only our own window to draw into a memory bitmap.
            app.StartPosition = FormStartPosition.Manual;
            app.Location = new Point(SystemInformation.VirtualScreen.Right + 200,0);
            app.Show();
            Check(!app.Bounds.IntersectsWith(SystemInformation.VirtualScreen),"test window remains outside all visible displays");
            Snapshot(app,"dashboard-initial");
            Button translate = Field<Button>(app,"translateButton");
            TextBox input = Field<TextBox>(app,"input");
            Check(!translate.Enabled && !Field<Button>(app,"copyTranscript").Enabled,"empty setup disables translation and transcript actions");
            Run(app,"ShowSessionPage","audio");
            Check(Field<Label>(app,"audioDeviceHint").Visible,"the empty device selector explains its state on Audio setup");
            Run(app,"ShowSessionPage","live");
            AddFixtures(app);
            Check(!translate.Enabled,"empty composer stays disabled with a connected engine");
            input.Text = "一緒に行きましょう。";
            Check(translate.Enabled,"typing enables translation when connected");
            input.Focus();
            Check(input.Focused,"keyboard focus reaches the composer");
            input.Text = String.Join(Environment.NewLine, new string[40]).Replace(Environment.NewLine,"one line"+Environment.NewLine);
            Check(input.ScrollBars == ScrollBars.Vertical,"overflowing pasted text reveals a scroll bar");
            input.Text = "一緒に行きましょう。";
            Check(input.ScrollBars == ScrollBars.None,"shorter text releases the scroll gutter");
            input.Select(input.TextLength,0);
            SendMessage(app.Handle,0x0127,new IntPtr(0x10002),IntPtr.Zero);
            Field<Button>(app,"pickLanguage").Focus();
            RichTextBox captions = Field<RichTextBox>(app,"output");
            Check(captions.Text.Contains("Shall we go together?") && captions.Text.Contains("같이 갈까요?"),"native transcript includes generated English and source scripts");
            Check(Field<Label>(app,"transcriptCount").Text == "3 captions","caption count follows delivered entries");
            Snapshot(app,"dashboard-captions-fixture");
            Field<CheckBox>(app,"showSource").Checked = false;
            Check(!captions.Text.Contains("같이 갈까요?") && captions.Text.Contains("Shall we go together?"),"source toggle hides the original and preserves English");
            Field<CheckBox>(app,"showSource").Checked = true;
            app.Size = new Size(900,620);
            Snapshot(app,"dashboard-small");
            Check(captions.Width >= 260 && input.Width >= 240,"transcript and composer remain usable at the 900 × 620 minimum");
            Check(Field<Label>(app,"regionLabel").Width > 130,"hidden Japanese direction selector releases the display label width");
            Run(app,"SelectProfile","ja");
            var direction = Field<ComboBox>(app,"japaneseDirection");
            Check(direction.Visible && direction.Width >= 85 && Field<Label>(app,"regionLabel").Width > 100,"Japanese direction and display label both fit the compact rail");
            Run(app,"SelectProfile","auto");
            Run(app,"ToggleSessionDetails");
            Button setup = Field<Button>(app,"setupProfile");
            Panel railScroll = setup.Parent as Panel;
            while (railScroll != null && !railScroll.AutoScroll) railScroll = railScroll.Parent as Panel;
            Check(railScroll != null,"additional language controls have a scrollable page");
            railScroll.ScrollControlIntoView(setup);
            Application.DoEvents();
            Check(railScroll.RectangleToScreen(railScroll.ClientRectangle).IntersectsWith(setup.RectangleToScreen(setup.ClientRectangle)),"compact page scrolls through to language setup controls");
            railScroll.AutoScrollPosition = Point.Empty;
            Run(app,"ToggleSessionDetails");
            app.Size = new Size(1160,745);
            app.Scale(new SizeF(1.5F,1.5F));
            Snapshot(app,"dashboard-layout-150pct");
            Console.WriteLine("150% simulated sizes: editor " + input.Size + ", transcript " + captions.Size + ", source " + Field<Button>(app,"pickLanguage").Size);
            Check(input.Width >= 550 && input.Height >= input.Font.Height && captions.Height >= 185 && Field<Button>(app,"pickLanguage").Width > 300,"150% layout simulation keeps essential controls usable");
            CheckTypedRequests(app);
            Field<Button>(app,"clearTranscript").PerformClick();
            Check(captions.TextLength == 0 && !Field<Button>(app,"copyTranscript").Enabled && Field<Label>(app,"emptyOutput").Visible,"clearing restores the dashboard empty state");
            Check(Field<Process>(app,"worker") == null && !Field<bool>(app,"audioWanted") && !Field<bool>(app,"screenWanted"),"no worker, audio stream or screen capture was started");
            Console.WriteLine(passed + " UI checks passed.");
        }
    }
}
