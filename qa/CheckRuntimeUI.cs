using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

// Load exactly the supplied executable. The form stays hidden, all outgoing worker
// commands end in a memory stream, and playback is explicitly disabled.
internal static class CheckRuntimeUI
{
    const BindingFlags Flags = BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance;
    static int checks, failures;
    static object Get(object o, string name) { return o.GetType().GetField(name, Flags).GetValue(o); }
    static void Put(object o, string name, object value) { o.GetType().GetField(name, Flags).SetValue(o, value); }
    static object Call(object o, string name, params object[] args) { return o.GetType().GetMethod(name, Flags).Invoke(o, args); }
    static Dictionary<string,object> Row(params object[] items)
    {
        var result = new Dictionary<string, object>();
        for (int i=0; i<items.Length; i+=2) result.Add((string)items[i], items[i+1]);
        return result;
    }
    static void Message(object form, params object[] items) { Call(form, "HandleMessage", Row(items)); }
    static void Check(bool ok, string label)
    {
        checks++;
        if (!ok) failures++;
        Console.WriteLine((ok ? "PASS " : "FAIL ") + label);
    }
    static bool TickOn(object form, string toggle) { return (bool)Get(form,toggle).GetType().GetProperty("Checked").GetValue(Get(form,toggle),null); }

    [STAThread]
    static int Main(string[] args)
    {
        var app = Assembly.LoadFrom(Path.GetFullPath(args[0]));
        using (var form = (Form)Activator.CreateInstance(app.GetType("LiveTranslate.MainForm",true),true))
        using (var buffer = new MemoryStream())
        using (var identity = Process.GetCurrentProcess())
        {
            Put(form,"worker",identity);
            Put(form,"inputWriter",new StreamWriter(buffer) {AutoFlush=true});
            Put(form,"screenArmed",false);
            ((CheckBox)Get(form,"overlayToggle")).Checked=false;
            var prefs=Get(form,"voicePrefs");
            prefs.GetType().GetProperty("Enabled").SetValue(prefs,false,null);
            var history=(IList)Get(form,"history");
            var vr=Get(form,"vrCaptionState");
            var devices=(ComboBox)Get(form,"devices");
            var pc=Row("id",-2,"kind","pc","name","System default");
            var mic=Row("id",7,"kind","microphone","name","Test mic");
            var ja=Row("code","ja","name","Japanese","text_ready",true,"screen_ready",true,"speech_language","ja","ocr_language","jpn");
            Message(form,"type","status","installed_languages",new object[]{ja},"profiles",new object[]{ja},"speech_models",new[]{"base","small"});
            Check((bool)Get(form,"connected") && !(bool)Get(form,"audioWanted"),"Engine readiness keeps listening off");
            Message(form,"type","devices","devices",new object[]{mic,pc});
            Check(Convert.ToInt32(Get(devices.SelectedItem,"DeviceId"))==-2,"Playback is selected ahead of microphones");
            devices.SelectedIndex=0;
            Message(form,"type","devices","devices",new object[]{pc,mic});
            Check(Convert.ToInt32(Get(devices.SelectedItem,"DeviceId"))==7,"Refresh preserves a deliberately selected microphone after reordering");
            var toggle=Get(form,"audioToggle");
            toggle.GetType().GetProperty("Checked").SetValue(toggle,true,null);
            string audio=(string)Get(form,"audioSession");
            Check((bool)Get(form,"audioWanted") && audio.Length>0,"Audio toggle creates a new session");
            Message(form,"type","audio","session_id",audio,"language","ja","text","One.","original","一");
            Check(history.Count==1 && (string)Call(vr,"Read",0,0L)=="One.","Current speech reaches the transcript and caption state");
            Message(form,"type","audio","session_id",audio,"language","en-GB","text","One.","original","One.");
            Check(history.Count==1,"English speech does not reach captions");
            Call(form,"SelectProfile","ko");
            string next=(string)Get(form,"audioSession");
            Check(next!=audio && (bool)Get(form,"audioWanted") && Call(vr,"Read",0,0L)==null,"Language switch rotates audio session and clears the old caption");
            Message(form,"type","audio","session_id",audio,"language","ja","text","Late.","original","遅い");
            Message(form,"type","capture_state","channel","audio","session_id",audio,"state","stopped");
            Check(history.Count==1 && (bool)Get(form,"audioWanted"),"Previous audio results and stop events cannot interrupt the new source");
            Message(form,"type","devices","devices",new object[]{pc});
            Check(!(bool)Get(form,"audioWanted") && !TickOn(form,"audioToggle"),"Removing the active input stops listening");
            Message(form,"type","audio","session_id",next,"language","ko","text","Late.","original","늦다");
            Check(history.Count==1,"A removed device cannot publish late captions");
            Call(form,"SelectProfile","ja");
            Put(form,"oneShotPending",true);
            Put(form,"onceSession","one");
            Message(form,"type","screen_once","session_id","one","language","ja","text","Signs.","original","標識");
            Check(history.Count==2 && (string)Call(vr,"Read",1,0L)=="Signs.","A completed one-shot publishes exactly one screen caption");
            Call(form,"SelectProfile","ko");
            Check(Call(vr,"Read",1,0L)==null,"Changing source clears the previous one-shot overlay when watching is paused");
            Message(form,"type","screen_once","session_id","one","language","ja","text","Signs.","original","標識");
            Check(history.Count==2,"Completed one-shot ignores a late duplicate");
            Call(form,"SelectProfile","ja");
            Call(form,"SelectDisplay",@"\\.\UNPLUGGED-TEST-DISPLAY");
            Check(((Rectangle)Call(form,"CaptureBounds")).IsEmpty,"A missing named monitor never falls back to the primary monitor");
            Check(!((Button)Get(form,"readOnce")).Enabled,"Read once is disabled for a missing target");
            Check(((Label)Get(form,"regionLabel")).Text.IndexOf("unavailable",StringComparison.OrdinalIgnoreCase)>=0,"Missing selected display is identified");
            var changed = System.Windows.Forms.Message.Create(form.Handle,0x007e,IntPtr.Zero,IntPtr.Zero);
            Call(form,"WndProc",changed);
            Application.DoEvents();
            Check((string)Get(form,"targetDisplay")==@"\\.\UNPLUGGED-TEST-DISPLAY","A display-change notification retains the named target");
            Rectangle primary=SystemInformation.VirtualScreen;
            Put(form,"selectedRegion",new Rectangle(primary.Right+100,primary.Bottom+100,80,40));
            Check(((Rectangle)Call(form,"CaptureBounds")).IsEmpty,"An unplugged region cannot silently retarget another screen");
            Call(form,"WndProc",changed);
            Application.DoEvents();
            Check(Get(form,"selectedRegion")!=null,"A display-change notification preserves an unavailable region for recovery");
            Call(form,"SelectDisplay",new object[]{null});
            Check(!((Rectangle)Call(form,"CaptureBounds")).IsEmpty && ((Button)Get(form,"readOnce")).Enabled,"Selecting an available monitor restores the action");
            Put(form,"screenWanted",true); Put(form,"screenArmed",true); Put(form,"screenSession","watch");
            Message(form,"type","screen","session_id","watch","language","ja","text","Watch.","original","見る");
            Call(form,"HandleWorkerExit",identity); // Disposes our extra process handle, never stops a process.
            Check(!(bool)Get(form,"connected") && !(bool)Get(form,"screenWanted") && (bool)Get(form,"screenArmed"),"A disconnect preserves screen intent and retires capture");
            Check(Get(form,"worker")==null && Get(form,"inputWriter")==null && ((IDictionary)Get(form,"pending")).Count==0,"Disconnected worker and pending requests are released");
            Check(Call(vr,"Read",0,0L)==null && Call(vr,"Read",1,0L)==null,"Disconnect clears visible caption state");
            int prior=history.Count;
            Message(form,"type","screen","session_id","watch","language","ja","text","Late.","original","遅い");
            Check(history.Count==prior && !form.Visible,"A late disconnected capture is ignored without opening the dashboard");
            Put(form,"screenArmed",false);
            Message(form,"type","status","installed_languages",new object[]{ja},"profiles",new object[]{ja},"speech_models",new[]{"base","small"});
            Check(!devices.Enabled && !((Control)toggle).Enabled,"A reconnected engine must confirm the old device list before listening can start");
            Message(form,"type","devices","devices",new object[]{pc});
            Check(devices.Enabled && ((Control)toggle).Enabled && !(bool)Get(form,"audioWanted"),"Fresh device enumeration permits listening and leaves it off");
        }
        Console.WriteLine((checks-failures)+"/"+checks+" runtime interaction checks passed");
        return failures==0 ? 0 : 1;
    }
}
