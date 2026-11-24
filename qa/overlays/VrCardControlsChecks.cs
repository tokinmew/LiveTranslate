// Authored, off-screen Windows fixtures. No live capture, audio, model downloads, or production data.
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
namespace LiveTranslate {
internal static class VrCardControlsChecks {
 [DllImport("user32.dll",CharSet=CharSet.Unicode,EntryPoint="GetPropW")] static extern IntPtr GetProp(IntPtr h,string n);
 [DllImport("user32.dll")] static extern bool GetWindowDisplayAffinity(IntPtr h,out uint a);
 [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr h,IntPtr dc,uint f);
 static int count;
 static void Check(bool b,string message) { if(!b)throw new Exception(message); Console.WriteLine("PASS "+message);count++; }
 static T Find<T>(Control c,string name) where T:Control { if(c is T && c.AccessibleName==name)return (T)c; foreach(Control child in c.Controls){var v=Find<T>(child,name);if(v!=null)return v;}return null; }
 static void Save(Form w,string p) { w.Refresh();Application.DoEvents();using(var b=new Bitmap(w.ClientSize.Width,w.ClientSize.Height))using(var g=Graphics.FromImage(b)){IntPtr dc=g.GetHdc();try{Check(PrintWindow(w.Handle,dc,3),"Caption HWND rendered through ordinary PrintWindow");}finally{g.ReleaseHdc(dc);}b.Save(p,ImageFormat.Png);} }
 [STAThread] static int Main(string[] args) { try {
  Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
  var state=new VrCaptionState(); long now=VrCaptionWindow.Clock.ElapsedMilliseconds;
  state.Present("audio","The next train arrives in three minutes.","次の電車は３分後に到着します。","Japanese",now);
  using(var w=new VrCaptionWindow(state)) {
   w.Location=new Point(-23000,-23000);w.Show();Application.DoEvents();
   var status=Find<Control>(w,"Translation capture status");
   Check(status.Text=="Ready","Existing text alone never claims capture is listening");
   bool paused=false;int dashboard=0,settings=0,pauseCalls=0;
   w.StatusProvider=delegate{return paused?"Paused":"Listening";};w.PausedProvider=delegate{return paused;};w.CanPauseProvider=delegate{return true;};w.InputSourceProvider=delegate{return "System audio";};
   w.PauseRequested=delegate{pauseCalls++;paused=!paused;};w.OpenDashboardRequested=delegate{dashboard++;};w.OpenSettingsRequested=delegate{settings++;};w.RefreshCaptions();Application.DoEvents();
   var original=Find<RichTextBox>(w,"Speech original");var english=Find<RichTextBox>(w,"Speech translation");
   Check(original.Visible && original.Text=="次の電車は３分後に到着します。" && english.Text=="The next train arrives in three minutes.","Original and English stay complete in separate selectable controls");
   Check(original.ForeColor.B>original.ForeColor.G && english.ForeColor.R>240,"Original uses purple and translated caption uses white");
   Check(status.Text=="Listening" && Find<Label>(w,"Capture input").Text=="System audio","Capture status and input reflect supplied session state");
   var pin=Find<Button>(w,"Pin window");pin.PerformClick();Check(w.TopMost && pin.AccessibleName=="Unpin window","Pin enables actual TopMost window behavior");pin.PerformClick();Check(!w.TopMost,"Unpin restores ordinary window ordering");
   Find<Button>(w,"Pause translation").PerformClick();Check(paused && pauseCalls==1 && Find<Button>(w,"Resume translation").Text=="Resume" && status.Text=="Paused","Pause invokes session control and refreshes truthful Resume state");
   Find<Button>(w,"Resume translation").PerformClick();Check(!paused && pauseCalls==2 && status.Text=="Listening","Resume invokes the same session control");
   Find<Button>(w,"Open dashboard").PerformClick();Find<Button>(w,"Settings").PerformClick();Check(dashboard==1 && settings==1,"Dashboard and settings dispatch their real callbacks");
   uint affinity;Check(GetProp(w.Handle,VrCaptionWindow.CaptureMarker)!=IntPtr.Zero && GetWindowDisplayAffinity(w.Handle,out affinity) && affinity==0,"Caption retains its exclusion marker without capture-hiding affinity");
   IntPtr foreground=GetForegroundWindow();
   state.Present("audio","Please wait by the platform.","ホームでお待ちください。","Japanese",VrCaptionWindow.Clock.ElapsedMilliseconds);
   w.RefreshCaptions();Application.DoEvents();
   Check(GetForegroundWindow()==foreground && original.Text=="ホームでお待ちください。" && english.Text=="Please wait by the platform.","A new original/translation frame preserves foreground focus");
   Save(w,Path.Combine(args[0],"floating-card-preview.png"));
   w.Size=w.MinimumSize;Application.DoEvents();
   foreach(string name in new[]{"Caption source","Pause translation","Open dashboard","Settings","Pin window","Speech original","Speech translation"}) { var c=Find<Control>(w,name);Check(c!=null && c.Visible && w.ClientRectangle.Contains(w.RectangleToClient(c.RectangleToScreen(c.ClientRectangle))),"Minimum size contains "+name); }
   Save(w,Path.Combine(args[0],"floating-card-minimum.png"));
   w.OpenSettingsRequested=null;w.OpenDashboardRequested=null;w.PauseRequested=null;w.RefreshCaptions();Check(!Find<Button>(w,"Settings").Enabled && !Find<Button>(w,"Open dashboard").Enabled && !Find<Button>(w,"Pause translation").Enabled,"Unavailable callbacks leave actions disabled");
   w.Close();
  }
  state.Present("text","Answer","Original","Japanese",10);Check(state.Original(2,120011)==null && state.SourceLabel(2,120011)==null,"Original metadata expires with its caption");
  state.Present("screen","Sign","Source","Japanese",10);state.Clear("screen");Check(state.Read(1,11)==null && state.Original(1,11)==null,"Clearing a channel removes original metadata");
  Console.WriteLine(count+" new caption controls checks passed.");return 0;
 }catch(Exception e){Console.Error.WriteLine(e);return 1;} }
}
}