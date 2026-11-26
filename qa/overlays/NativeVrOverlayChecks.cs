using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Reflection;
using System.Text;
using System.Windows.Forms;
using LiveTranslate;

internal static class NativeVrOverlayChecks
{
    static int checks;
    static void Check(bool value, string description) { if (!value) throw new Exception(description); checks++; }
    sealed class FakeApi : INativeVrOverlayApi
    {
        internal int Starts, Configurations, Submissions, Disposals;
        internal float Width, Distance, Vertical;
        internal byte[] Pixels;
        internal NativeVrApiEvents Events;
        internal string Fail;
        public void Start() { Starts++; if (Fail == "start") throw new Exception("Start failed"); }
        public void Configure(float width, float distance, float vertical)
        { Configurations++; Width = width; Distance = distance; Vertical = vertical; if (Fail == "placement") throw new Exception("Placement failed"); }
        public void Submit(byte[] rgba, int width, int height)
        {
            Submissions++; Pixels = rgba;
            Check(width == 1024 && height == 512 && rgba.Length == 1024 * 512 * 4, "Correct raw texture shape");
            if (Fail == "image") throw new Exception("Image failed");
        }
        public NativeVrApiEvents Poll() { NativeVrApiEvents answer = Events; Events = new NativeVrApiEvents(); return answer; }
        public void Dispose() { Disposals++; }
    }

    [STAThread]
    static int Main(string[] args)
    {
        try
        {
            string output = args.Length == 0 ? Path.GetTempPath() : args[0];
            Directory.CreateDirectory(output);
            Lifecycle(); PagingAndPixels(output); Binding(); Trust(output); Integration();
            Console.WriteLine("Native VR overlay checks passed: " + checks + ". Native display still requires a real SteamVR headset field test.");
            return 0;
        }
        catch (Exception e) { Console.Error.WriteLine(e); return 1; }
    }

    static void Lifecycle()
    {
        long now = 100;
        var fake = new FakeApi();
        int factories = 0;
        using (var overlay = new NativeVrOverlay(delegate { factories++; return fake; }, delegate { return now; }))
        {
            Check(!overlay.IsRunning && factories == 0, "Opening settings does not initialize SteamVR");
            var source = new NativeVrCaptionSnapshot { Status = "Translation paused", Input = "System audio", Original = "こんにちは", Translation = "Hello." };
            overlay.Update(source);
            source.Translation = "This external mutation must not replace the copied caption.";
            Check(fake.Submissions == 0, "Captions alone do not start VR");
            string error;
            Check(overlay.Start(out error) && error == null && overlay.IsRunning, "Explicit start connects");
            Check(fake.Starts == 1 && fake.Configurations == 1 && fake.Submissions == 1, "First true caption submitted once");
            Check(fake.Width == .9F && fake.Distance == 1.6F && fake.Vertical == -.4F, "Default head-relative readable placement");
            Check(overlay.Start(out error) && fake.Starts == 1, "Repeated start does not reinitialize runtime");
            byte[] oldPixels = fake.Pixels;
            for (int i = 0; i < 100; i++) { now += 1; Check(overlay.Tick(out error), "Pending image stays alive"); }
            Check(fake.Submissions == 1 && Object.ReferenceEquals(fake.Pixels, oldPixels), "Pending texture is not overwritten");
            overlay.Update(new NativeVrCaptionSnapshot { Status = "Listening", Input = "VRChat audio", Translation = "The newest accepted translation." });
            now += 400;
            Check(overlay.Tick(out error) && fake.Submissions == 1, "New captions wait for the asynchronous image load");
            fake.Events = new NativeVrApiEvents { ImageLoaded = true };
            Check(overlay.Tick(out error) && fake.Submissions == 2, "Image completion submits the latest queued caption");
            fake.Events = new NativeVrApiEvents { ImageLoaded = true };
            Check(overlay.Tick(out error), "Second image acknowledged");
            int submissions = fake.Submissions;
            for (int i = 0; i < 1000; i++) { now += 1; Check(overlay.Tick(out error), "Unchanged caption remains connected"); }
            Check(fake.Submissions == submissions, "Unchanged captions do not upload repeated textures");
            overlay.WidthMeters = 100; overlay.DistanceMeters = Single.NaN; overlay.VerticalOffsetMeters = -100;
            Check(overlay.Tick(out error) && fake.Width == 1.4F && fake.Distance == 1.6F && fake.Vertical == -.9F, "Placement rejects nonfinite and out-of-range values");
            overlay.Update(new NativeVrCaptionSnapshot { Status = "Translation paused", Input = "No capture running" });
            Check(overlay.Tick(out error) && fake.Submissions == submissions + 1, "Expired or cleared captions replace the old image");
            fake.Events = new NativeVrApiEvents { ImageLoaded = true };
            Check(overlay.Tick(out error), "Cleared image acknowledged");
            fake.Events = new NativeVrApiEvents { Closed = true };
            Check(!overlay.Tick(out error) && !overlay.IsRunning && error.Contains("SteamVR closed"), "Runtime closure is reported honestly");
            Check(fake.Disposals == 1, "Runtime closure releases resources once");
            overlay.Stop(); Check(fake.Disposals == 1, "Repeated stop is harmless");
        }
        foreach (string stage in new[] { "start", "placement", "image" })
        {
            var failed = new FakeApi { Fail = stage };
            using (var overlay = new NativeVrOverlay(delegate { return failed; }, delegate { return now; }))
            {
                string error;
                Check(!overlay.Start(out error) && !overlay.IsRunning && !String.IsNullOrEmpty(error), "Failed " + stage + " is visible");
                Check(failed.Disposals == 1, "Failed " + stage + " releases resources");
            }
        }
        var timeout = new FakeApi();
        using (var overlay = new NativeVrOverlay(delegate { return timeout; }, delegate { return now; }))
        {
            string error; Check(overlay.Start(out error), "Timeout fixture starts");
            now += 16000;
            Check(!overlay.Tick(out error) && error.Contains("did not finish"), "Stalled compositor times out without overwriting its memory");
            Check(timeout.Disposals == 1, "Timeout releases native resources");
        }
        var imageFailure = new FakeApi();
        using (var overlay = new NativeVrOverlay(delegate { return imageFailure; }, delegate { return now; }))
        {
            string error; Check(overlay.Start(out error), "Image-failure fixture starts");
            imageFailure.Events = new NativeVrApiEvents { ImageFailed = true };
            Check(!overlay.Tick(out error) && error.Contains("could not display"), "Image load failure is reported");
        }
        var restart = new FakeApi();
        using (var overlay = new NativeVrOverlay(delegate { return restart; }, delegate { return now; }))
        {
            overlay.Update(new NativeVrCaptionSnapshot { Original = "古い字幕", Translation = "This caption has expired before restart." });
            string error; Check(overlay.Start(out error), "Restart fixture first displays its accepted caption");
            overlay.Stop(); now += 200000;
            Check(String.IsNullOrEmpty(Field<NativeVrCaptionSnapshot>(overlay, "latest").Translation), "Stopping discards the cached caption snapshot");
            Check(overlay.Start(out error), "Restart reconnects after the old caption expires");
            NativeVrCaptionSnapshot firstRestartImage = Field<NativeVrCaptionSnapshot>(overlay, "drawn");
            Check(String.IsNullOrEmpty(firstRestartImage.Translation) && String.IsNullOrEmpty(firstRestartImage.Original), "First restart image contains no stale original or translation");
            Check(restart.Submissions == 2, "Restart submits the cleared image before any fresh caption arrives");
        }
    }

    static string Compact(string value)
    {
        var result = new StringBuilder(); foreach (char c in value) if (!Char.IsWhiteSpace(c)) result.Append(c); return result.ToString();
    }
    static void PagingAndPixels(string output)
    {
        var text = new StringBuilder();
        for (int i = 0; i < 70; i++) text.Append("Sentence " + i + ": Please tell me where the train station is. 日本語の文章です。 👋 ");
        List<string> pages = NativeVrCaptionPainter.Pages(text.ToString());
        Check(pages.Count > 3, "Long translations have multiple readable pages");
        Check(Compact(String.Join("", pages.ToArray())) == Compact(text.ToString()), "No translated words are discarded between pages");
        foreach (string page in pages)
        {
            Check(page.Length > 0 && !Char.IsLowSurrogate(page[0]) && !Char.IsHighSurrogate(page[page.Length - 1]), "Pages preserve surrogate pairs");
        }
        var source = new NativeVrCaptionSnapshot { Status = "Listening", Input = "System audio + VRChat window", Original = "今日は駅まで案内してもらえますか？", Translation = "Could you show me the way to the station today?" };
        using (Bitmap image = NativeVrCaptionPainter.Render(source, 0))
        {
            image.Save(Path.Combine(output, "native-vr-caption.png"), ImageFormat.Png);
            Check(image.GetPixel(0, 0).A == 0 && image.GetPixel(4, 256).A > 200, "Transparent corners and readable shaded panel");
            Check(image.Width == 1024 && image.Height == 512, "Texture has fixed bounded dimensions");
        }
        source.Translation = text.ToString();
        using (Bitmap image = NativeVrCaptionPainter.Render(source, 1)) image.Save(Path.Combine(output, "native-vr-long-caption.png"), ImageFormat.Png);
        using (var image = new Bitmap(2, 1, PixelFormat.Format32bppArgb))
        {
            image.SetPixel(0, 0, Color.FromArgb(255, 200, 50, 10)); image.SetPixel(1, 0, Color.FromArgb(128, 20, 40, 180));
            byte[] rgba = NativeVrCaptionPainter.Rgba(image);
            Check(rgba[0] == 200 && rgba[1] == 50 && rgba[2] == 10 && rgba[3] == 255, "Red and blue channels use SteamVR RGBA order");
            Check(rgba[4] == 20 && rgba[5] == 40 && rgba[6] == 180 && rgba[7] == 128, "Alpha is preserved without opaque desktop background");
        }
        long now = 0; var fake = new FakeApi();
        using (var overlay = new NativeVrOverlay(delegate { return fake; }, delegate { return now; }))
        {
            overlay.Update(source); string error;
            Check(overlay.Start(out error), "Long-caption overlay starts");
            byte[] first = fake.Pixels;
            fake.Events = new NativeVrApiEvents { ImageLoaded = true };
            now += 8600;
            Check(overlay.Tick(out error) && fake.Submissions == 2, "Long translation advances to the next page");
            Check(!Object.ReferenceEquals(first, fake.Pixels), "New page has its own queued image");
        }
    }

    static void Binding()
    {
        var notifications = new NativeVrApiEvents(); notifications.Record(701);
        Check(!notifications.Closed, "Another process quitting does not close our overlay");
        notifications.Record(508); notifications.Record(517);
        Check(notifications.ImageLoaded && notifications.ImageFailed && !notifications.Closed, "Image notifications decode independently of runtime closure");
        notifications.Record(534); Check(notifications.Closed, "Targeted overlay close notification is honored");
        notifications = new NativeVrApiEvents(); notifications.Record(700); Check(notifications.Closed, "Runtime quit request is honored");
        Check(IntPtr.Size == 8 && Marshal.SizeOf(typeof(NativeVrMatrix34)) == 48, "64-bit OpenVR matrix ABI is 48 bytes");
        Check(NativeVrOverlayFunctions.Version == "FnTable:IVROverlay_027", "Function offsets cannot bind an unversioned interface");
        IntPtr table = Marshal.AllocHGlobal(61 * IntPtr.Size);
        var alive = new List<Delegate>();
        try
        {
            for (int i = 0; i <= 60; i++) Marshal.WriteIntPtr(table, i * IntPtr.Size, IntPtr.Zero);
            Action<int, Delegate> slot = delegate(int index, Delegate function) { alive.Add(function); Marshal.WriteIntPtr(table, index * IntPtr.Size, Marshal.GetFunctionPointerForDelegate(function)); };
            int created = 0, destroyed = 0, shown = 0, hidden = 0;
            slot(1, new NativeVrOverlayFunctions.CreateDelegate(delegate(string key, string name, ref ulong handle) { created++; Check(key == "key" && name == "caption", "Create arguments round-trip"); handle = 42; return 0; }));
            slot(2, new NativeVrOverlayFunctions.HandleDelegate(delegate(ulong h) { destroyed++; Check(h == 42, "Destroy handle is 64 bit"); return 0; }));
            slot(21, new NativeVrOverlayFunctions.FloatDelegate(delegate(ulong h, float w) { Check(h == 42 && w == .9F, "Width slot has correct ABI"); return 0; }));
            slot(34, new NativeVrOverlayFunctions.TransformDelegate(delegate(ulong h, uint device, ref NativeVrMatrix34 matrix) { Check(h == 42 && device == 0 && matrix.M7 == -.4F && matrix.M11 == -1.6F && matrix.M0 == 1 && matrix.M5 == 1 && matrix.M10 == 1, "Head-relative placement has correct coordinates and ABI"); return 0; }));
            slot(41, new NativeVrOverlayFunctions.HandleDelegate(delegate(ulong h) { shown++; return 0; }));
            slot(42, new NativeVrOverlayFunctions.HandleDelegate(delegate(ulong h) { hidden++; return 0; }));
            slot(46, new NativeVrOverlayFunctions.PollDelegate(delegate(ulong h, IntPtr e, uint size) { Check(h == 42 && size == 64, "Event ABI uses Windows 64-byte record"); Marshal.WriteInt32(e, 508); return true; }));
            slot(60, new NativeVrOverlayFunctions.RawDelegate(delegate(ulong h, IntPtr p, uint w, uint height, uint depth) { Check(h == 42 && p == new IntPtr(17) && w == 1024 && height == 512 && depth == 4, "Raw image ABI round-trips bytes and dimensions"); return 0; }));
            var functions = new NativeVrOverlayFunctions(table);
            ulong createdHandle = 0; Check(functions.Create("key", "caption", ref createdHandle) == 0 && createdHandle == 42, "Function-table create works");
            functions.Width(createdHandle, .9F); NativeVrMatrix34 headTransform = NativeVrMatrix34.Placement(1.6F, -.4F); functions.Transform(createdHandle, 0, ref headTransform);
            functions.Show(createdHandle); functions.Hide(createdHandle); functions.Raw(createdHandle, new IntPtr(17), 1024, 512, 4); functions.Destroy(createdHandle);
            IntPtr data = Marshal.AllocHGlobal(64);
            try { Check(functions.Poll(createdHandle, data, 64) && Marshal.ReadInt32(data) == 508, "Byte-size event return is marshalled correctly"); }
            finally { Marshal.FreeHGlobal(data); }
            Check(created == 1 && destroyed == 1 && shown == 1 && hidden == 1, "Exact official function slots were invoked");
            Marshal.WriteIntPtr(table, 34 * IntPtr.Size, IntPtr.Zero);
            bool rejected = false; try { new NativeVrOverlayFunctions(table); } catch (InvalidOperationException) { rejected = true; }
            Check(rejected, "Incomplete table fails closed before calling a null function");
        }
        finally { GC.KeepAlive(alive); Marshal.FreeHGlobal(table); }
    }

    static void Trust(string output)
    {
        string path, reason;
        if (!SteamVrRuntimePath.Find(out path, out reason)) { Console.WriteLine("Installed-runtime trust probe unavailable: " + reason); return; }
        Check(File.Exists(path) && ValveSignature.Valid(path), "Installed runtime DLL has a valid Valve signature");
        IntPtr library = NativeVrExports.LoadLibraryEx(path, IntPtr.Zero, 0x100 | 0x800);
        try { Check(library != IntPtr.Zero, "Trusted runtime can be loaded without starting SteamVR"); new NativeVrExports(library); checks++; }
        finally { if (library != IntPtr.Zero) NativeVrExports.FreeLibrary(library); }
        string tampered = Path.Combine(output, "altered-runtime-never-loaded.dll");
        byte[] bytes = File.ReadAllBytes(path); bytes[512] ^= 1; File.WriteAllBytes(tampered, bytes);
        Check(!ValveSignature.Valid(tampered), "A modified runtime DLL is rejected before loading");
        File.Delete(tampered);
        Console.WriteLine("Verified installed Valve runtime and required exported entry points. No VR initialization or headset access was performed by this probe.");
    }

    const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    static T Field<T>(object owner, string name) { return (T)owner.GetType().GetField(name, Instance).GetValue(owner); }
    static void Put(object owner, string name, object value) { owner.GetType().GetField(name, Instance).SetValue(owner, value); }
    static void Call(object owner, string name, params object[] args) { owner.GetType().GetMethod(name, Instance).Invoke(owner, args); }
    static void Isolate(Form form)
    {
        var events = (EventHandlerList)typeof(Component).GetProperty("Events", Instance).GetValue(form, null);
        foreach (string name in new[] { "EVENT_LOAD", "EVENT_SHOWN" })
        {
            object key = typeof(Form).GetField(name, BindingFlags.Static | BindingFlags.NonPublic).GetValue(null);
            if (events[key] != null) events.RemoveHandler(key, events[key]);
        }
        form.ShowInTaskbar = false; form.StartPosition = FormStartPosition.Manual;
        form.Location = new Point(SystemInformation.VirtualScreen.Right + 200, 0);
    }
    static void Integration()
    {
        Application.EnableVisualStyles();
        var app = new MainForm();
        try
        {
            Isolate(app); app.Show(); Application.DoEvents();
            Check(Field<object>(app, "worker") == null, "Isolated app starts no capture worker");
            Check(Field<NativeVrOverlay>(app, "nativeVrOverlay") == null && !Field<Timer>(app, "nativeVrTimer").Enabled, "Startup leaves native overlay and timer off");
            Check(Field<Button>(app, "nativeVrStart").Enabled && !Field<Button>(app, "nativeVrStop").Enabled, "VR settings advertise explicit start and disabled stop");
            Form settings = Field<Form>(app, "settingsForm"); Isolate(settings);
            Call(app, "OpenSettingsSection", "VR captions"); Application.DoEvents();
            Check(Field<TabControl>(app, "settingsTabs").SelectedTab.Text == "VR captions", "Native VR tab is accessible from Settings");
            Check(Field<NativeVrOverlay>(app, "nativeVrOverlay") == null, "Opening the VR tab starts no runtime");
            var fake = new FakeApi();
            long now = 0;
            var overlay = new NativeVrOverlay(delegate { return fake; }, delegate { return now; });
            Put(app, "nativeVrOverlay", overlay);
            Field<OpacitySlider>(app, "nativeVrOpacity").Value = 0;
            Call(app, "StartNativeVrCaptions");
            Check(Field<NativeVrCaptionSnapshot>(overlay, "drawn").BackgroundOpacity == 0, "The first submitted image honors saved transparent background without an opaque flash");
            Check(overlay.IsRunning && Field<Timer>(app, "nativeVrTimer").Enabled && fake.Starts == 1, "Explicit VR control starts one overlay and its app timer");
            Check(Field<VrCaptionWindow>(app, "vrCaptionWindow") == null, "Native overlay creates no desktop caption window");
            Check(!Field<Button>(app, "nativeVrStart").Enabled && Field<Button>(app, "nativeVrStop").Enabled, "Running state has correct start and stop controls");
            VrCaptionState state = Field<VrCaptionState>(app, "vrCaptionState");
            state.Present("audio", "Please meet at the station.", "駅で会いましょう。", "Japanese", VrCaptionWindow.Clock.ElapsedMilliseconds);
            fake.Events = new NativeVrApiEvents { ImageLoaded = true };
            Call(app, "RefreshNativeVrCaption");
            NativeVrCaptionSnapshot real = Field<NativeVrCaptionSnapshot>(overlay, "latest");
            Check(real.Translation == "Please meet at the station." && real.Original == "駅で会いましょう。", "Native overlay receives actual accepted caption state");
            Check(real.Status != "Listening", "A retained caption alone does not fabricate listening status");
            app.WindowState = FormWindowState.Minimized; Application.DoEvents();
            Check(overlay.IsRunning && Field<Timer>(app, "nativeVrTimer").Enabled, "Minimizing the dashboard leaves native captions running");
            state.Clear(null); fake.Events = new NativeVrApiEvents { ImageLoaded = true }; Call(app, "RefreshNativeVrCaption");
            real = Field<NativeVrCaptionSnapshot>(overlay, "latest");
            Check(String.IsNullOrEmpty(real.Translation) && String.IsNullOrEmpty(real.Original), "Clearing shared captions clears the native overlay snapshot");
            Call(app, "StopNativeVrCaptions", "Test stop");
            Check(!overlay.IsRunning && !Field<Timer>(app, "nativeVrTimer").Enabled && fake.Disposals == 1, "Stop button path stops updates and disposes the runtime");
            Check(Field<Button>(app, "nativeVrStart").Enabled && !Field<Button>(app, "nativeVrStop").Enabled && Field<Label>(app, "nativeVrStatus").Text == "Test stop", "Stopped state retains an honest user-facing status");
            var closingFake = new FakeApi();
            Put(app, "nativeVrOverlay", new NativeVrOverlay(delegate { return closingFake; }, delegate { return now; }));
            Call(app, "StartNativeVrCaptions");
            app.Dispose();
            Check(closingFake.Disposals == 1, "Closing the application destroys its active native overlay");
        }
        finally { app.Dispose(); }
    }
}
