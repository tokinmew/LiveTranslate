using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal static class CheckReplyPractice
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    [DllImport("user32", CharSet=CharSet.Unicode, ExactSpelling=true)]
    static extern IntPtr GetPropW(IntPtr window, string key);
    [DllImport("user32")] static extern bool PrintWindow(IntPtr window, IntPtr dc, uint flags);
    static int passed;
    static T Field<T>(Form main, string name) { return (T)main.GetType().GetField(name, Private).GetValue(main); }
    static void Put(Form main, string name, object value) { main.GetType().GetField(name, Private).SetValue(main,value); }
    static void Run(Form main, string method, params object[] args) { main.GetType().GetMethod(method, Private).Invoke(main,args); }
    static void Check(bool value,string label) {
        if (!value) throw new InvalidOperationException(label);
        ++passed; Console.WriteLine("PASS " + label);
    }
    static Control Find(Control owner,string text) {
        foreach (Control child in owner.Controls) {
            if (child.Text == text) return child;
            var found = Find(child,text); if (found != null) return found;
        }
        return null;
    }
    static void Select(ComboBox list,string text) {
        int index = list.FindStringExact(text);
        if (index < 0) throw new InvalidOperationException("Missing option " + text);
        list.SelectedIndex = index;
    }
    static Dictionary<string,object> Reply(int id, string txt, string reading) {
        return new Dictionary<string,object>{{"id",id},{"type","practice_reply"},{"target","ja"},{"text",txt},
            {"pronunciation",reading},{"pronunciation_scheme","Japanese rōmaji (Hepburn)"},{"method","phrasebook"}};
    }
    static void ShowOutsideDisplays(Form window) {
        var events = (EventHandlerList)typeof(Component).GetProperty("Events",Private).GetValue(window,null);
        var key = typeof(Form).GetField("EVENT_LOAD", BindingFlags.NonPublic | BindingFlags.Static).GetValue(null);
        events.RemoveHandler(key,events[key]); // Bypass FitToDisplay for the synthetic screenshot.
        window.StartPosition = FormStartPosition.Manual;
        window.Location = new Point(SystemInformation.VirtualScreen.Right + 200,0);
        window.Show();
        Application.DoEvents();
        Check(!window.Bounds.IntersectsWith(SystemInformation.VirtualScreen), "Only the offscreen reply window is rendered");
    }
    static void Snapshot(Form window,string path) {
        using (var image = new Bitmap(window.ClientSize.Width,window.ClientSize.Height))
        using (Graphics g = Graphics.FromImage(image)) {
            IntPtr dc = g.GetHdc();
            try { Check(PrintWindow(window.Handle,dc,3),"Native reply window rendered into the fixture image"); }
            finally { g.ReleaseHdc(dc); }
            image.Save(path,ImageFormat.Png);
        }
    }
    [STAThread] static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        var type=Assembly.LoadFrom(Path.GetFullPath(args[0])).GetType("LiveTranslate.MainForm", true);
        using (Form main=(Form)Activator.CreateInstance(type,true))
        using (var stream=new MemoryStream())
        using (var writer=new StreamWriter(stream))
        using (var fake=Process.GetCurrentProcess()) {
            Check(Find(main,"Practice a reply") is Button,"Dashboard has a reply-practice entry");
            Run(main,"BuildReplyPractice");
            Form window=Field<Form>(main,"practiceWindow");
            ShowOutsideDisplays(window);
            try {
                Check(GetPropW(window.Handle,"LiveTranslate.ReplyPractice") == new IntPtr(1),"Native reply window has its OCR exclusion marker");
                var draft=Field<TextBox>(main,"practiceDraft");
                var target=Field<ComboBox>(main,"practiceTarget");
                var examples=Field<ComboBox>(main,"practiceExamples");
                var action=Field<Button>(main,"practiceAction");
                var translation=Field<RichTextBox>(main,"practiceTranslation");
                var reading=Field<RichTextBox>(main,"practiceReading");
                var status=Field<Label>(main,"practiceStatus");
                var note=Field<RichTextBox>(main,"practiceNote");
                Check(!action.Enabled && !main.Visible && Field<object>(main,"worker")==null,"Unprepared dashboard keeps reply submission disabled");
                Check(target.Items.Count==4 && examples.Items.Count==6 && draft.MaxLength==500,"Four starter targets, five starter phrases and input limit");
                Put(main,"connected",true);
                Put(main,"worker",fake);
                Put(main,"inputWriter",writer);
                Run(main,"UpdateReplyTargets",new Dictionary<string,object>{{"reply_targets",new string[]{"ja","ko","zh","zt","fr"}},{"multilingual_text_ready",false}});
                Select(target,"Japanese");
                Select(examples,"Thank you");
                Check(action.Enabled && draft.Text=="Thank you","Starter phrase available without optional model");
                Select(target,"fr");
                Check(!action.Enabled && status.Text.Contains("multilingual"),"Expanded target offers setup when model is missing");
                Run(main,"UpdateReplyTargets",new Dictionary<string,object>{{"reply_targets",new string[]{"ja","ko","zh","zt","fr"}},{"multilingual_text_ready",true}});
                Run(main,"RefreshPracticeControls");
                Check(action.Enabled,"Expanded target works after model readiness update");
                Select(target,"Japanese");
                Run(main,"SubmitPracticeReply");
                int id=Field<int>(main,"practicePending");
                Run(main,"SubmitPracticeReply");
                Check(id>0 && Field<int>(main,"requestId")==id && !action.Enabled,"Rapid submissions enqueue a single reply");
                draft.Text="Changed before the result.";
                Run(main,"HandleMessage",Reply(id,"old","old"));
                Check(translation.Text=="" && reading.Text=="" && action.Enabled,"A late reply cannot overwrite a changed draft");
                Select(examples,"Thank you");
                Run(main,"SubmitPracticeReply");
                id=Field<int>(main,"practicePending");
                var incoming=Reply(id,"ありがとうございます。","Arigatō gozaimasu.");
                incoming["pronunciation_note"]="Approximate sound: ah-ree-gah-toh goh-zah-ee-mahss. A bar over a vowel means to hold it longer.";
                Run(main,"HandleMessage",incoming);
                Check(translation.Text=="ありがとうございます。" && reading.Text=="Arigatō gozaimasu.","Translation and pronunciation appear in separately selectable fields");
                Check(Field<Label>(main,"practiceScheme").Text.Contains("Hepburn") && Field<Button>(main,"practiceCopyReading").Enabled,"Reading guide labels the system and permits manual copying");
                Check(Field<IList>(main,"history").Count==0 && Field<RichTextBox>(main,"output").TextLength==0,"Outgoing content stays outside live caption history");
                translation.SelectAll();
                Check(translation.SelectedText==translation.Text && reading.ReadOnly && translation.ReadOnly,"Read-only target text remains selectable");
                translation.Select(0,0);
                window.Update();
                if (args.Length > 1) Snapshot(window,args[1]);
                Run(main,"SubmitPracticeReply"); id=Field<int>(main,"practicePending");
                var partial=Reply(id,"ありがとうございます。","");
                partial["pronunciation_note"]="No pronunciation available.";
                Run(main,"HandleMessage",partial);
                Check(translation.TextLength>0 && reading.TextLength==0 && !Field<Button>(main,"practiceCopyReading").Enabled &&
                    note.Text=="No pronunciation available.","An unavailable reading preserves the translated words");
                Run(main,"SubmitPracticeReply"); id=Field<int>(main,"practicePending");
                Run(main,"HandleMessage",new Dictionary<string,object>{{"id",id},{"type","error"},{"message","Optional model is missing."}});
                Check(action.Enabled && status.Text.Contains("missing") && Field<IList>(main,"history").Count==0,"Reply errors remain scoped and permit a retry");
                Run(main,"SubmitPracticeReply"); id=Field<int>(main,"practicePending");
                Select(target,"Korean");
                Run(main,"HandleMessage",Reply(id,"old","old"));
                Check(translation.Text=="" && reading.Text=="","Changing the target discards an old language result");
                Run(main,"SubmitPracticeReply");
                Put(main,"connected",false);
                Run(main,"ResetPracticeConnection");
                Check(Field<int>(main,"practicePending")==0 && !action.Enabled,"Worker loss clears in-flight state");
                window.ClientSize=new Size(450,390); Application.DoEvents();
                var scroll=(Panel)window.Controls[0];
                Check(scroll.VerticalScroll.Visible && !scroll.HorizontalScroll.Visible && reading.Width>280,"Compact reply window scrolls vertically without clipping text fields");
                note.Text=new string('x',230);
                note.SelectAll();
                Check(note.ReadOnly && note.WordWrap && note.SelectedText.Length==230 && note.ScrollBars==RichTextBoxScrollBars.Vertical,
                    "The complete pronunciation note is selectable and scrollable at the minimum window width");
                Check(!main.Visible && !Field<bool>(main,"audioWanted") && !Field<bool>(main,"screenWanted"),"No screen or audio stream started");
            }
            finally {
                Put(main,"worker",null); Put(main,"inputWriter",null); window.Close(); window.Dispose();
            }
        }
        Console.WriteLine(passed+" native reply UI checks passed.");
    }
}
