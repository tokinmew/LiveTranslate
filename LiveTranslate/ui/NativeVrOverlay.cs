using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Web.Script.Serialization;

namespace LiveTranslate
{
    internal sealed class NativeVrCaptionSnapshot
    {
        internal string Status, Input, Original, Translation;
        internal int BackgroundOpacity = 95;
        internal NativeVrCaptionSnapshot Copy()
        {
            return new NativeVrCaptionSnapshot { Status = Status, Input = Input, Original = Original, Translation = Translation, BackgroundOpacity = BackgroundOpacity };
        }
        internal bool SameAs(NativeVrCaptionSnapshot other)
        {
            return other != null && Status == other.Status && Input == other.Input && Original == other.Original && Translation == other.Translation && BackgroundOpacity == other.BackgroundOpacity;
        }
    }

    // SteamVR renders this image directly. It is independent of desktop HWNDs,
    // monitor arrangement, the foreground application, and the desktop caption card.
    internal sealed class NativeVrOverlay : IDisposable
    {
        readonly Func<INativeVrOverlayApi> createApi;
        readonly Func<long> clock;
        readonly Stopwatch watch = Stopwatch.StartNew();
        INativeVrOverlayApi api;
        NativeVrCaptionSnapshot latest = new NativeVrCaptionSnapshot();
        NativeVrCaptionSnapshot drawn;
        long changedAt, submittedAt;
        int drawnPage = -1, pageCount = 1;
        string pagedTranslation;
        bool pendingImage, placementDirty = true;
        float width = .9F, distance = 1.6F, vertical = -.4F;

        internal NativeVrOverlay() { createApi = delegate { return new SteamVrOverlayApi(); }; clock = delegate { return watch.ElapsedMilliseconds; }; }
        internal NativeVrOverlay(Func<INativeVrOverlayApi> factory, Func<long> milliseconds) { createApi = factory; clock = milliseconds; }
        internal bool IsRunning { get { return api != null; } }
        internal float WidthMeters { get { return width; } set { width = Clamp(value, .35F, 1.4F, .9F); placementDirty = true; } }
        internal float DistanceMeters { get { return distance; } set { distance = Clamp(value, .7F, 3F, 1.6F); placementDirty = true; } }
        internal float VerticalOffsetMeters { get { return vertical; } set { vertical = Clamp(value, -.9F, .2F, -.4F); placementDirty = true; } }
        static float Clamp(float value, float low, float high, float fallback) { return Single.IsNaN(value) || Single.IsInfinity(value) ? fallback : Math.Max(low, Math.Min(high, value)); }

        internal bool Start(out string error)
        {
            error = null;
            if (IsRunning) return true;
            INativeVrOverlayApi candidate = null;
            try
            {
                candidate = createApi();
                candidate.Start();
                api = candidate;
                placementDirty = true;
                drawn = null; drawnPage = -1; pendingImage = false;
                changedAt = clock();
                return Tick(out error);
            }
            catch (Exception e)
            {
                if (candidate != null) candidate.Dispose();
                api = null;
                error = e.GetBaseException().Message;
                return false;
            }
        }

        internal void Update(NativeVrCaptionSnapshot snapshot)
        {
            snapshot = snapshot ?? new NativeVrCaptionSnapshot();
            if (latest.SameAs(snapshot)) return;
            bool differentCaption = latest.Translation != snapshot.Translation || latest.Original != snapshot.Original;
            latest = snapshot.Copy();
            if (differentCaption) changedAt = clock();
        }

        // Call on the UI thread approximately every 100 ms, including while the
        // dashboard is minimized. No new texture is generated for an unchanged page.
        internal bool Tick(out string error)
        {
            error = null;
            if (api == null) return false;
            try
            {
                NativeVrApiEvents events = api.Poll();
                if (events.Closed) throw new InvalidOperationException("SteamVR closed the caption overlay. Start it again after reconnecting your headset.");
                if (events.ImageFailed) throw new InvalidOperationException("SteamVR could not display the caption image. Restart the VR overlay.");
                if (events.ImageLoaded) pendingImage = false;
                if (placementDirty) { api.Configure(width, distance, vertical); placementDirty = false; }
                long now = clock();
                if (pendingImage)
                {
                    if (now - submittedAt > 15000) throw new InvalidOperationException("SteamVR did not finish loading the caption image. Restart the VR overlay.");
                    return true;
                }
                if (pagedTranslation != latest.Translation)
                { pageCount = NativeVrCaptionPainter.PageCount(latest.Translation); pagedTranslation = latest.Translation; }
                int page = pageCount <= 1 ? 0 : (int)(((now - changedAt) / 8500L) % pageCount);
                if (!latest.SameAs(drawn) || page != drawnPage)
                {
                    using (Bitmap image = NativeVrCaptionPainter.Render(latest, page))
                        api.Submit(NativeVrCaptionPainter.Rgba(image), image.Width, image.Height);
                    drawn = latest.Copy(); drawnPage = page; pendingImage = true; submittedAt = now;
                }
                return true;
            }
            catch (Exception e)
            {
                error = e.GetBaseException().Message;
                Stop();
                return false;
            }
        }

        internal void ApplyPlacement() { placementDirty = true; }
        internal void Stop()
        {
            INativeVrOverlayApi old = api;
            api = null; pendingImage = false; drawn = null; drawnPage = -1;
            latest = new NativeVrCaptionSnapshot();
            pagedTranslation = null; pageCount = 1; changedAt = clock();
            if (old != null) { try { old.Dispose(); } catch { } }
        }
        public void Dispose() { Stop(); }
    }

    internal struct NativeVrApiEvents
    {
        internal bool ImageLoaded, ImageFailed, Closed;
        internal void Record(int type)
        {
            if (type == 508) ImageLoaded = true;
            else if (type == 517) ImageFailed = true;
            else if (type == 700 || type == 534) Closed = true;
            // ProcessQuit (701) describes a process and may concern another app.
            // Runtime exit is detected separately; do not mistake it for our quit request.
        }
    }
    internal interface INativeVrOverlayApi : IDisposable
    {
        void Start();
        void Configure(float width, float distance, float vertical);
        void Submit(byte[] rgba, int width, int height);
        NativeVrApiEvents Poll();
    }

    internal static class NativeVrCaptionPainter
    {
        internal const int Width = 1024, Height = 512;
        internal static int PageCount(string text) { return Pages(text).Count; }
        internal static List<string> Pages(string text)
        {
            var pages = new List<string>();
            text = (text ?? "").Trim();
            if (text.Length == 0) { pages.Add(""); return pages; }
            using (var image = new Bitmap(1, 1))
            using (Graphics graphics = Graphics.FromImage(image))
            using (var font = new Font("Segoe UI", 37F, FontStyle.Bold, GraphicsUnit.Pixel))
            using (var format = new StringFormat(StringFormatFlags.LineLimit))
            {
                graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                while (text.Length != 0)
                {
                    int fit, lines;
                    graphics.MeasureString(text, font, new SizeF(Width - 88, 270), format, out fit, out lines);
                    fit = Math.Min(text.Length, Math.Max(1, fit));
                    if (fit < text.Length && fit > 1 && Char.IsHighSurrogate(text[fit - 1])) fit--;
                    if (fit < text.Length && !Char.IsWhiteSpace(text[fit - 1]) && !Char.IsWhiteSpace(text[fit]))
                    {
                        int space = text.LastIndexOf(' ', fit - 1, fit);
                        if (space > fit / 2) fit = space + 1;
                    }
                    pages.Add(text.Substring(0, fit).Trim());
                    text = text.Substring(fit).TrimStart();
                }
            }
            return pages;
        }

        internal static Bitmap Render(NativeVrCaptionSnapshot snapshot, int page)
        {
            snapshot = snapshot ?? new NativeVrCaptionSnapshot();
            List<string> pages = Pages(snapshot.Translation);
            page = Math.Max(0, Math.Min(pages.Count - 1, page));
            var image = new Bitmap(Width, Height, PixelFormat.Format32bppArgb);
            using (Graphics graphics = Graphics.FromImage(image))
            {
                graphics.Clear(Color.Transparent);
                graphics.SmoothingMode = SmoothingMode.AntiAlias;
                graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
                int opacity = Math.Max(0, Math.Min(100, snapshot.BackgroundOpacity));
                int backgroundAlpha = (int)Math.Round(opacity * 255.0 / 100);
                using (GraphicsPath shape = Rounded(new Rectangle(2, 2, Width - 5, Height - 5), 24))
                using (var background = new SolidBrush(Color.FromArgb(backgroundAlpha, 15, 20, 30)))
                using (var border = new Pen(Color.FromArgb(opacity * 180 / 100, 69, 91, 105), 2))
                { graphics.FillPath(background, shape); graphics.DrawPath(border, shape); }
                using (var heading = new Font("Segoe UI", 25F, FontStyle.Bold, GraphicsUnit.Pixel))
                using (var status = new Font("Segoe UI", 21F, FontStyle.Regular, GraphicsUnit.Pixel))
                using (var original = new Font("Segoe UI", 25F, FontStyle.Regular, GraphicsUnit.Pixel))
                using (var translation = new Font("Segoe UI", 37F, FontStyle.Bold, GraphicsUnit.Pixel))
                using (var white = new SolidBrush(Color.FromArgb(250, 251, 255)))
                using (var mint = new SolidBrush(Color.FromArgb(92, 238, 205)))
                using (var purple = new SolidBrush(Color.FromArgb(193, 180, 255)))
                using (var muted = new SolidBrush(Color.FromArgb(192, 203, 218)))
                using (var clipped = new StringFormat { Trimming = StringTrimming.EllipsisCharacter, FormatFlags = StringFormatFlags.NoWrap })
                using (var paragraph = new StringFormat(StringFormatFlags.LineLimit))
                {
                    graphics.DrawString("LiveTranslate", heading, white, new RectangleF(38, 25, 300, 40), clipped);
                    using (var right = new StringFormat(clipped))
                    {
                        right.Alignment = StringAlignment.Far;
                        graphics.DrawString(snapshot.Status ?? "", status, mint, new RectangleF(348, 29, 635, 34), right);
                    }
                    using (var line = new Pen(Color.FromArgb(backgroundAlpha, 80, 112, 128))) graphics.DrawLine(line, 38, 79, Width - 38, 79);
                    graphics.DrawString(snapshot.Original ?? "", original, purple, new RectangleF(40, 97, Width - 80, 77), paragraph);
                    string text = pages[page].Length == 0 ? "No translation yet" : pages[page];
                    graphics.DrawString(text, translation, pages[page].Length == 0 ? muted : white, new RectangleF(40, 181, Width - 88, 270), paragraph);
                    graphics.DrawString(snapshot.Input ?? "", status, muted, new RectangleF(40, 465, Width - 250, 31), clipped);
                    if (pages.Count > 1)
                    {
                        using (var right = new StringFormat(clipped))
                        { right.Alignment = StringAlignment.Far; graphics.DrawString("Page " + (page + 1) + " / " + pages.Count, status, mint, new RectangleF(Width - 232, 465, 192, 31), right); }
                    }
                }
            }
            return image;
        }

        static GraphicsPath Rounded(Rectangle r, int radius)
        {
            var path = new GraphicsPath(); int d = radius * 2;
            path.AddArc(r.Left, r.Top, d, d, 180, 90); path.AddArc(r.Right - d, r.Top, d, d, 270, 90);
            path.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90); path.AddArc(r.Left, r.Bottom - d, d, d, 90, 90); path.CloseFigure();
            return path;
        }

        // GDI stores BGRA. SetOverlayRaw consumes RGBA, four bytes per pixel.
        internal static byte[] Rgba(Bitmap image)
        {
            BitmapData data = image.LockBits(new Rectangle(0, 0, image.Width, image.Height), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            try
            {
                var pixels = new byte[checked(image.Width * image.Height * 4)];
                for (int y = 0; y < image.Height; y++)
                    Marshal.Copy(IntPtr.Add(data.Scan0, y * data.Stride), pixels, y * image.Width * 4, image.Width * 4);
                for (int i = 0; i < pixels.Length; i += 4) { byte red = pixels[i + 2]; pixels[i + 2] = pixels[i]; pixels[i] = red; }
                return pixels;
            }
            finally { image.UnlockBits(data); }
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct NativeVrMatrix34
    {
        internal float M0, M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11;
        internal static NativeVrMatrix34 Placement(float distance, float vertical)
        { return new NativeVrMatrix34 { M0 = 1, M5 = 1, M10 = 1, M7 = vertical, M11 = -distance }; }
    }

    // These slots are ONLY the versioned IVROverlay_027 C function table from
    // Valve's v2.5.1 headers/openvr_capi.h. Never reuse them for another version.
    // https://github.com/ValveSoftware/openvr/blob/v2.5.1/headers/openvr_capi.h
    internal sealed class NativeVrOverlayFunctions
    {
        internal const string Version = "FnTable:IVROverlay_027";
        [UnmanagedFunctionPointer(CallingConvention.StdCall, CharSet = CharSet.Ansi)]
        internal delegate int CreateDelegate(string key, string name, ref ulong handle);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] internal delegate int HandleDelegate(ulong handle);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] internal delegate int FloatDelegate(ulong handle, float value);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] internal delegate int TransformDelegate(ulong handle, uint device, ref NativeVrMatrix34 transform);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] internal delegate int RawDelegate(ulong handle, IntPtr rgba, uint width, uint height, uint bytesPerPixel);
        [UnmanagedFunctionPointer(CallingConvention.StdCall)] [return: MarshalAs(UnmanagedType.I1)]
        internal delegate bool PollDelegate(ulong handle, IntPtr vrEvent, uint eventSize);
        internal readonly CreateDelegate Create;
        internal readonly HandleDelegate Destroy, Show, Hide;
        internal readonly FloatDelegate Width;
        internal readonly TransformDelegate Transform;
        internal readonly RawDelegate Raw;
        internal readonly PollDelegate Poll;
        internal NativeVrOverlayFunctions(IntPtr table)
        {
            if (table == IntPtr.Zero) throw new InvalidOperationException("SteamVR did not provide its overlay interface.");
            Create = Bind<CreateDelegate>(table, 1); Destroy = Bind<HandleDelegate>(table, 2);
            Width = Bind<FloatDelegate>(table, 21); Transform = Bind<TransformDelegate>(table, 34);
            Show = Bind<HandleDelegate>(table, 41); Hide = Bind<HandleDelegate>(table, 42);
            Poll = Bind<PollDelegate>(table, 46); Raw = Bind<RawDelegate>(table, 60);
        }
        static T Bind<T>(IntPtr table, int slot) where T : class
        {
            IntPtr function = Marshal.ReadIntPtr(table, checked(slot * IntPtr.Size));
            if (function == IntPtr.Zero) throw new InvalidOperationException("The installed SteamVR overlay interface is incomplete. Update SteamVR.");
            return Marshal.GetDelegateForFunctionPointer(function, typeof(T)) as T;
        }
    }

    internal sealed class SteamVrOverlayApi : INativeVrOverlayApi
    {
        static readonly object Ownership = new object();
        static bool hasOwner;
        bool owns, initialized;
        IntPtr library, pixels, events;
        ulong overlay;
        NativeVrOverlayFunctions functions;
        NativeVrExports.ShutdownDelegate shutdown;
        readonly Stopwatch runtimeWatch = Stopwatch.StartNew();
        long nextRuntimeCheck;
        const int EventSize = 64;

        public void Start()
        {
            if (overlay != 0) return;
            lock (Ownership)
            {
                if (hasOwner) throw new InvalidOperationException("A native VR caption overlay is already running in LiveTranslate.");
                hasOwner = owns = true;
            }
            try
            {
                string path, reason;
                if (!SteamVrRuntimePath.Find(out path, out reason)) throw new InvalidOperationException(reason);
                if (!IsSteamVrRunning()) throw new InvalidOperationException("Start SteamVR, connect your headset and launch VRChat through SteamVR. Then start native VR captions.");
                library = NativeVrExports.LoadLibraryEx(path, IntPtr.Zero, 0x100 | 0x800);
                if (library == IntPtr.Zero) throw new InvalidOperationException("Windows could not load the installed SteamVR overlay library. Verify SteamVR's installed files.");
                var exports = new NativeVrExports(library);
                shutdown = exports.Shutdown;
                if (!exports.HmdPresent()) throw new InvalidOperationException("SteamVR cannot see a connected headset. Connect it, then start native VR captions again.");
                int error = 0;
                exports.Init(ref error, 2); // VRApplication_Overlay, never a scene/game application.
                if (error != 0) throw new InvalidOperationException("SteamVR could not start captions (error " + error + "). Connect the headset and restart the VR overlay.");
                initialized = true;
                IntPtr table = exports.Interface(NativeVrOverlayFunctions.Version, ref error);
                if (error != 0 || table == IntPtr.Zero) throw new InvalidOperationException("This SteamVR installation does not support the caption overlay interface. Update SteamVR.");
                functions = new NativeVrOverlayFunctions(table);
                Check(functions.Create("org.tokinmew.livetranslate.captions." + Process.GetCurrentProcess().Id, "LiveTranslate captions", ref overlay), "create captions");
                if (overlay == 0) throw new InvalidOperationException("SteamVR returned an empty caption overlay handle.");
                events = Marshal.AllocHGlobal(EventSize);
                pixels = Marshal.AllocHGlobal(NativeVrCaptionPainter.Width * NativeVrCaptionPainter.Height * 4);
            }
            catch { Dispose(); throw; }
        }

        internal static bool IsSteamVrRunning()
        {
            Process[] processes = Process.GetProcessesByName("vrserver");
            try { return processes.Length != 0; }
            finally { foreach (Process process in processes) process.Dispose(); }
        }
        static void Check(int code, string action)
        {
            if (code != 0) throw new InvalidOperationException("SteamVR could not " + action + " (overlay error " + code + "). Restart the VR overlay.");
        }
        public void Configure(float width, float distance, float vertical)
        {
            if (overlay == 0) throw new InvalidOperationException("Start native VR captions first.");
            Check(functions.Width(overlay, width), "resize captions");
            NativeVrMatrix34 transform = NativeVrMatrix34.Placement(distance, vertical);
            Check(functions.Transform(overlay, 0, ref transform), "position captions"); // tracked HMD, never a wrist/controller.
        }
        public void Submit(byte[] rgba, int width, int height)
        {
            if (overlay == 0) throw new InvalidOperationException("Start native VR captions first.");
            if (width != NativeVrCaptionPainter.Width || height != NativeVrCaptionPainter.Height || rgba == null || rgba.Length != width * height * 4)
                throw new ArgumentException("The VR caption texture has an invalid size.");
            Marshal.Copy(rgba, 0, pixels, rgba.Length);
            Check(functions.Raw(overlay, pixels, (uint)width, (uint)height, 4), "load the caption image");
            Check(functions.Show(overlay), "show captions");
        }
        public NativeVrApiEvents Poll()
        {
            var result = new NativeVrApiEvents();
            if (runtimeWatch.ElapsedMilliseconds >= nextRuntimeCheck)
            {
                nextRuntimeCheck = runtimeWatch.ElapsedMilliseconds + 2000;
                if (!IsSteamVrRunning()) { result.Closed = true; return result; }
            }
            for (int i = 0; i < 32 && functions.Poll(overlay, events, EventSize); i++)
            {
                result.Record(Marshal.ReadInt32(events));
            }
            return result;
        }
        public void Dispose()
        {
            if (overlay != 0 && functions != null)
            {
                try { functions.Hide(overlay); } catch { }
                try { functions.Destroy(overlay); } catch { }
            }
            overlay = 0; functions = null;
            if (initialized && shutdown != null) { try { shutdown(); } catch { } }
            initialized = false; shutdown = null;
            // SetOverlayRaw can load asynchronously. Keep its source buffer until
            // the image-loaded event allows reuse, or until overlay shutdown.
            if (pixels != IntPtr.Zero) { Marshal.FreeHGlobal(pixels); pixels = IntPtr.Zero; }
            if (events != IntPtr.Zero) { Marshal.FreeHGlobal(events); events = IntPtr.Zero; }
            if (library != IntPtr.Zero) { NativeVrExports.FreeLibrary(library); library = IntPtr.Zero; }
            if (owns) { lock (Ownership) { hasOwner = false; owns = false; } }
        }
    }

    internal sealed class NativeVrExports
    {
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] internal delegate uint InitDelegate(ref int error, int appType);
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] internal delegate void ShutdownDelegate();
        [UnmanagedFunctionPointer(CallingConvention.Cdecl, CharSet = CharSet.Ansi)] internal delegate IntPtr InterfaceDelegate(string version, ref int error);
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] [return: MarshalAs(UnmanagedType.I1)] internal delegate bool HmdDelegate();
        internal readonly InitDelegate Init;
        internal readonly ShutdownDelegate Shutdown;
        internal readonly InterfaceDelegate Interface;
        internal readonly HmdDelegate HmdPresent;
        internal NativeVrExports(IntPtr library)
        {
            Init = Export<InitDelegate>(library, "VR_InitInternal"); Shutdown = Export<ShutdownDelegate>(library, "VR_ShutdownInternal");
            Interface = Export<InterfaceDelegate>(library, "VR_GetGenericInterface"); HmdPresent = Export<HmdDelegate>(library, "VR_IsHmdPresent");
        }
        static T Export<T>(IntPtr library, string name) where T : class
        {
            IntPtr pointer = GetProcAddress(library, name);
            if (pointer == IntPtr.Zero) throw new InvalidOperationException("The installed SteamVR library is incomplete. Verify SteamVR's installed files.");
            return Marshal.GetDelegateForFunctionPointer(pointer, typeof(T)) as T;
        }
        [DllImport("kernel32.dll", EntryPoint = "LoadLibraryExW", CharSet = CharSet.Unicode, SetLastError = true)]
        internal static extern IntPtr LoadLibraryEx(string file, IntPtr reserved, uint flags);
        [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool FreeLibrary(IntPtr library);
        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true)] static extern IntPtr GetProcAddress(IntPtr library, string name);
    }

    internal static class SteamVrRuntimePath
    {
        internal static bool Find(out string path, out string reason)
        {
            var roots = new List<string>();
            string registration = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "openvr", "openvrpaths.vrpath");
            try
            {
                if (File.Exists(registration) && new FileInfo(registration).Length < 65536)
                {
                    var record = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(registration)) as Dictionary<string, object>;
                    object value;
                    if (record != null && record.TryGetValue("runtime", out value))
                    {
                        object[] entries = value as object[];
                        if (entries != null) foreach (object entry in entries) if (entry is string) roots.Add((string)entry);
                    }
                }
            }
            catch (Exception) { }
            string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            if (!String.IsNullOrEmpty(programFiles)) roots.Add(Path.Combine(programFiles, "Steam", "steamapps", "common", "SteamVR"));
            foreach (string root in roots)
            {
                try
                {
                    if (!Path.IsPathRooted(root) || root.StartsWith("\\\\", StringComparison.Ordinal)) continue;
                    string candidate = Path.GetFullPath(Path.Combine(root, "bin", "win64", "openvr_api.dll"));
                    if (File.Exists(candidate) && ValveSignature.Valid(candidate)) { path = candidate; reason = null; return true; }
                }
                catch (Exception) { }
            }
            path = null;
            reason = "A trusted SteamVR installation was not found. Install or repair SteamVR on this PC. Native captions require PC VR through SteamVR; standalone headsets are not supported.";
            return false;
        }
    }

    internal static class ValveSignature
    {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct TrustFile { internal uint Size; [MarshalAs(UnmanagedType.LPWStr)] internal string Path; internal IntPtr File, Subject; }
        [StructLayout(LayoutKind.Sequential)]
        struct TrustData
        {
            internal uint Size; internal IntPtr Policy, Sip; internal uint Ui, Revocation, Choice; internal IntPtr File;
            internal uint StateAction; internal IntPtr State, Url; internal uint Flags, UiContext; internal IntPtr Signature;
        }
        [DllImport("wintrust.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
        static extern int WinVerifyTrust(IntPtr window, ref Guid action, ref TrustData data);
        internal static bool Valid(string path)
        {
            var file = new TrustFile { Size = (uint)Marshal.SizeOf(typeof(TrustFile)), Path = path };
            IntPtr nativeFile = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(TrustFile)));
            try
            {
                Marshal.StructureToPtr(file, nativeFile, false);
                var data = new TrustData { Size = (uint)Marshal.SizeOf(typeof(TrustData)), Ui = 2, Choice = 1, File = nativeFile, Flags = 0x1000 };
                Guid action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");
                if (WinVerifyTrust(new IntPtr(-1), ref action, ref data) != 0) return false;
                using (var certificate = new X509Certificate2(X509Certificate.CreateFromSignedFile(path)))
                {
                    string publisher = certificate.GetNameInfo(X509NameType.SimpleName, false);
                    return publisher == "Valve Corp." || publisher == "Valve Corporation";
                }
            }
            catch (Exception) { return false; }
            finally { Marshal.DestroyStructure(nativeFile, typeof(TrustFile)); Marshal.FreeHGlobal(nativeFile); }
        }
    }
}
