using System;
using System.Collections.Generic;
using System.Reflection;
using System.IO;
using System.Runtime.InteropServices;
using System.Globalization;
using System.Threading;
using LiveTranslate;

class CheckSpeech
{
    class SilentVoice : ISpokenOutput
    {
        public bool Finished { get; set; }
        public List<string> Played = new List<string>();
        public int Stops, Disposes;
        public void Say(string text) { Played.Add(text); Finished = false; }
        public void Stop() { Stops++; }
        public void Dispose() { Disposes++; }
    }
    static int checks;
    static object Member(object owner,string name,BindingFlags flags,params object[] args)
    {
        return owner.GetType().InvokeMember(name,flags,null,owner,args,CultureInfo.InvariantCulture);
    }
    static void TestMemorySpeech(WindowsVoice installed)
    {
        object sapi = Field<object>(installed,"speaker");
        object sink = Activator.CreateInstance(Type.GetTypeFromProgID("SAPI.SpMemoryStream",true));
        object format = Member(sink,"Format",BindingFlags.GetProperty);
        try
        {
            Member(format,"Type",BindingFlags.SetProperty,18); // SAFT16kHz16BitMono
            Member(sapi,"AudioOutputStream",BindingFlags.SetProperty,sink);
            object bound = Member(sapi,"AudioOutputStream",BindingFlags.GetProperty);
            try { Check(Object.ReferenceEquals(bound,sink),"Memory output route verified before generating audio"); }
            finally { Marshal.ReleaseComObject(bound); }
            installed.Say("Please meet me at the station tomorrow.");
            DateTime end=DateTime.UtcNow.AddSeconds(15);
            while (!installed.Finished && DateTime.UtcNow<end) Thread.Sleep(30);
            Check(installed.Finished,"Memory synthesis completed");
            byte[] pcm=(byte[])Member(sink,"GetData",BindingFlags.InvokeMethod);
            Check(pcm.Length>=8000 && pcm.Length<=15*32000 && pcm.Length%2==0,"Plausible sample duration");
            int peak=0, active=0;
            for(int i=0;i<pcm.Length;i+=2)
            {
                int amplitude=Math.Abs((int)BitConverter.ToInt16(pcm,i));
                peak=Math.Max(peak,amplitude);
                if(amplitude>50) active++;
            }
            Check(active>1000 && peak>100,"Non-silent English speech signal");
            string wave=Path.Combine(Path.GetTempPath(),"LiveTranslate-voice-"+Guid.NewGuid().ToString("N")+".wav");
            try
            {
                using(var file=new BinaryWriter(new FileStream(wave,FileMode.CreateNew)))
                {
                    file.Write(System.Text.Encoding.ASCII.GetBytes("RIFF")); file.Write(36+pcm.Length);
                    file.Write(System.Text.Encoding.ASCII.GetBytes("WAVEfmt ")); file.Write(16);
                    file.Write((short)1); file.Write((short)1); file.Write(16000); file.Write(32000); file.Write((short)2); file.Write((short)16);
                    file.Write(System.Text.Encoding.ASCII.GetBytes("data")); file.Write(pcm.Length); file.Write(pcm);
                }
                Check(new FileInfo(wave).Length==pcm.Length+44,"WAV data size verified");
            }
            finally { File.Delete(wave); }
            Console.WriteLine("Installed English voice to private WAV via memory sink: {0} PCM bytes, {1:F2} s, peak {2}, {3} nonquiet samples. File removed.",pcm.Length,pcm.Length/32000.0,peak,active);
        }
        finally { Marshal.ReleaseComObject(format); Marshal.ReleaseComObject(sink); }
    }
    static void Check(bool pass, string reason) { if (!pass) throw new Exception(reason); checks++; }
    static T Field<T>(object form, string name) { return (T)form.GetType().GetField(name,BindingFlags.NonPublic | BindingFlags.Instance).GetValue(form); }
    static void Set(object form, string name, object value) { form.GetType().GetField(name,BindingFlags.NonPublic | BindingFlags.Instance).SetValue(form,value); }
    static void Call(object form, string name, params object[] args) { form.GetType().GetMethod(name,BindingFlags.NonPublic | BindingFlags.Instance).Invoke(form,args); }
    static Dictionary<string,object> Msg(string source,string session,string text,string original)
    {
        return new Dictionary<string,object>{{"channel","audio"},{"session_id",session},{"type","audio"},{"language",source},{"source","pc"},
                                                {"original",original},{"text",text}};
    }
    [STAThread] static void Main()
    {
        var voice = new SilentVoice();
        var queue = new SpokenQueue(voice);
        queue.Add("", 0); queue.Add(new string('x',2001), 0);
        Check(voice.Played.Count==0,"Invalid phrases ignored");
        queue.Add("Stop, please!", 100);
        Check(queue.Busy && voice.Played.Count==1,"First phrase starts immediately");
        Check(queue.IsOwnVoice("Stop please.",200) && !queue.IsOwnVoice("Please continue",200),"Own voice matched");
        foreach (string text in new string[]{"second","third","fourth","fifth"}) queue.Add(text, 300);
        voice.Finished=true; queue.Tick(400);
        Check(voice.Played[1]=="third","Bound queue discards oldest waiting");
        voice.Finished=true; queue.Tick(9000);
        Check(!queue.Busy && voice.Played.Count==2,"Expired queued captions are discarded");
        Check(!queue.IsOwnVoice("Stop please",9000) && queue.IsOwnVoice("third",9000),"Echo guard expires");
        queue.Add("last",9001); queue.Dispose();
        Check(voice.Stops==1 && voice.Disposes==1,"Stop purges output");
        using (var form = new MainForm())
        {
            var prefs = Field<VoiceOptions>(form,"voicePrefs");
            Check(!prefs.Enabled,"Reading off initially");
            Call(form,"HandleMessage",Msg("ja","old","stale","original"));
            Set(form,"audioWanted",true); Set(form,"audioSession","active");
            var silent = new SilentVoice();
            var installed = new SpokenQueue(silent);
            Set(form,"spokenQueue",installed);
            Call(form,"HandleMessage",Msg("ja","active","Silent mode","original"));
            Check(silent.Played.Count==0,"Captions stay silent when disabled");
            prefs.Enabled=true;
            Call(form,"HandleMessage",Msg("ja","old","Old audio","original"));
            Call(form,"HandleMessage",Msg("en","active","Already English","Already English"));
            Check(silent.Played.Count==0,"English and stale sessions stay silent");
            Call(form,"HandleMessage",Msg("ja","active","One moment.","Chotto matte"));
            Check(silent.Played.Count==1 && silent.Played[0]=="One moment.","Accepted audio reaches speaker");
            Call(form,"HandleMessage",Msg("ja","active","Feedback","One moment!"));
            silent.Finished=true; installed.Tick(1000);
            Check(!installed.Busy && silent.Played.Count==1,"Loopback feedback suppressed");
            Call(form,"StopAudio");
            Check(silent.Disposes==1 && Field<SpokenQueue>(form,"spokenQueue")==null,"Stopping capture releases speech output");
        }
        Console.WriteLine(checks + " silent queue and real UI event assertions passed.");
        using (var sapi = new WindowsVoice())
        {
            var voices = sapi.Tokens(true,null); var outputs = sapi.Tokens(false,null);
            Console.WriteLine("Local SAPI enumeration: " + voices.Count + " English voices, " + outputs.Count + " audio outputs.");
            if (voices.Count > 0)
            {
                sapi.Configure(new VoiceOptions{Voice=voices[0].Code,Output=outputs.Count==0?"":outputs[0].Code,Rate=1,Volume=30});
                Check(sapi.Finished,"Silent physical route idle");
                Console.WriteLine("Windows accepted voice, speed, volume and the selected or default output configuration.");
                TestMemorySpeech(sapi);
            }
        }
        Console.WriteLine(checks+" checks passed. No physical playback.");
    }
}
