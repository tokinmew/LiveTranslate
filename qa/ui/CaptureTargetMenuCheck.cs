using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Imaging;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using LiveTranslate;

// Generated, app-owned native windows. No capture worker or personal screen reads.
internal static class CaptureTargetMenuCheck
{
    const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wp, IntPtr lp);
    [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr window, IntPtr device, uint flags);
    static readonly List<Exception> failures = new List<Exception>();
    static ContextMenuStrip tracked;
    static int passed;
    static T Field<T>(MainForm form, string name) { return (T)typeof(MainForm).GetField(name, Instance).GetValue(form); }
    static void Put(MainForm form, string name, object value) { typeof(MainForm).GetField(name, Instance).SetValue(form, value); }
    static object Call(MainForm form, string name, params object[] args) { return typeof(MainForm).GetMethod(name, Instance).Invoke(form, args); }
    internal static void Track(ContextMenuStrip menu) { tracked = menu; menu.Opacity = 0; menu.DropShadowEnabled = false; }
    static ContextMenuStrip Menu(MainForm form)
    {
        FieldInfo field = typeof(MainForm).GetField("captureTargetMenu", Instance);
        return field == null ? tracked : (ContextMenuStrip)field.GetValue(form);
    }
    static void Check(bool success, string text)
    {
        if (!success) throw new InvalidOperationException(text);
        Console.WriteLine("PASS " + text); passed++;
    }
    static void Isolate(MainForm form)
    {
        EventHandlerList events = (EventHandlerList)typeof(Component).GetProperty("Events", Instance).GetValue(form, null);
        foreach (string name in new[] { "EVENT_LOAD", "EVENT_SHOWN" })
        {
            object key = typeof(Form).GetField(name, Static).GetValue(null);
            if (events[key] != null) events.RemoveHandler(key, events[key]);
        }
        form.Opacity = 0; form.ShowInTaskbar = false;
        form.StartPosition = FormStartPosition.Manual;
        form.Location = new Point(SystemInformation.VirtualScreen.Right + 200, 0);
        Put(form, "screenArmed", false);
        IntPtr handle = form.Handle;
        handle = Field<Button>(form, "selectArea").Handle;
        ContextMenuStrip menu = Menu(form);
        if (menu != null) Track(menu);
    }
    static void Pump()
    {
        for (int step = 0; step < 5; step++) { Application.DoEvents(); Thread.Sleep(2); }
        if (failures.Count != 0) throw new AggregateException("Native menu dispatch raised an exception.", failures);
    }
    static ContextMenuStrip Open(MainForm form)
    {
        Call(form, "ChooseTarget", Field<Button>(form, "selectArea"), EventArgs.Empty);
        ContextMenuStrip menu = Menu(form);
        if (menu == null) throw new InvalidOperationException("Capture menu was not available.");
        Track(menu); Pump();
        Check(menu.Visible && !menu.IsDisposed, "Capture menu opens as a live native popup");
        return menu;
    }
    static void NativeClick(ContextMenuStrip menu, ToolStripItem item)
    {
        Rectangle bounds = item.Bounds;
        int x = bounds.Left + bounds.Width / 2, y = bounds.Top + bounds.Height / 2;
        IntPtr point = new IntPtr((y << 16) | (x & 65535));
        IntPtr handle = menu.Handle;
        SendMessage(handle, 0x200, IntPtr.Zero, point);
        SendMessage(handle, 0x201, new IntPtr(1), point);
        SendMessage(handle, 0x202, IntPtr.Zero, point);
    }
    static Bitmap Render(ContextMenuStrip menu)
    {
        menu.Update();
        Bitmap image = new Bitmap(menu.Width, menu.Height);
        using (Graphics graphics = Graphics.FromImage(image))
        {
            IntPtr dc = graphics.GetHdc();
            try { if (!PrintWindow(menu.Handle, dc, 2)) throw new InvalidOperationException("Native menu render failed."); }
            finally { graphics.ReleaseHdc(dc); }
        }
        return image;
    }
    static int Pixels(Bitmap image, Rectangle bounds, Predicate<Color> match)
    {
        bounds.Intersect(new Rectangle(Point.Empty, image.Size));
        int found = 0;
        for (int y = bounds.Top; y < bounds.Bottom; y++)
            for (int x = bounds.Left; x < bounds.Right; x++) if (match(image.GetPixel(x, y))) found++;
        return found;
    }
    static void CheckAppearance(MainForm form, string directory)
    {
        ContextMenuStrip menu = Open(form);
        ToolStripMenuItem primary = (ToolStripMenuItem)menu.Items[0];
        Check(primary.Checked && primary.Text == "Primary display" && menu.Items[menu.Items.Count - 1].Text == "Draw an area…",
            "The themed capture popup retains its current-target check and action labels");
        var disabled = new ToolStripMenuItem("Unavailable fixture") { Enabled = false };
        menu.Items.Insert(1, disabled);
        menu.PerformLayout();
        Pump();
        using (Bitmap image = Render(menu))
        {
            image.Save(Path.Combine(directory, "capture-target-menu.png"), ImageFormat.Png);
            if (!SystemInformation.HighContrast)
            {
                Color face = image.GetPixel(image.Width - 9, primary.Bounds.Top + primary.Bounds.Height / 2);
                Check(face.GetBrightness() < .2F, "Actual native capture menu background renders dark");
                Check(image.GetPixel(0, image.Height / 2).GetBrightness() < .3F, "The native popup outline follows the quiet dark palette");
                Rectangle glyph = new Rectangle(0, primary.Bounds.Top, 28, primary.Bounds.Height);
                Check(Pixels(image, glyph, delegate(Color c) { return c.G > 140 && c.R < 120 && c.B > 90; }) > 2,
                    "The current-target checkmark remains visible in the native dark popup");
                Rectangle words = new Rectangle(30, primary.Bounds.Top, image.Width - 40, primary.Bounds.Height);
                Check(Pixels(image, words, delegate(Color c) { return c.R > 180 && c.G > 180 && c.B > 180; }) > 10,
                    "Enabled capture action text remains visible against the dark background");
                words = new Rectangle(30, disabled.Bounds.Top, image.Width - 40, disabled.Bounds.Height);
                Check(Pixels(image, words, delegate(Color c) { return c.R > 65 && c.R < 180 && c.G > 75 && c.G < 190 && c.B > 90 && c.B < 200; }) > 10,
                    "Disabled menu text stays readable in muted app colors");
            }
        }
        Rectangle bounds = primary.Bounds;
        SendMessage(menu.Handle, 0x200, IntPtr.Zero, new IntPtr(((bounds.Top + bounds.Height / 2) << 16) | (bounds.Left + bounds.Width / 2)));
        Pump();
        using (Bitmap image = Render(menu))
        {
            if (!SystemInformation.HighContrast)
                Check(image.GetPixel(image.Width - 9, bounds.Top + bounds.Height / 2).GetBrightness() < .3F,
                    "Hover selection retains a subdued dark surface");
            image.Save(Path.Combine(directory, "capture-target-menu-hover.png"), ImageFormat.Png);
        }
        NativeClick(menu, disabled); Pump();
        Check(menu.Visible && !Field<bool>(form, "captureTargetActionPending"), "Clicking a disabled capture menu item cannot dispatch work");
        menu.Close(); Pump();
    }
    static void Draw(MainForm form, bool accept)
    {
        Rectangle previous = new Rectangle(20, 25, 160, 80);
        Put(form, "selectedRegion", (Rectangle?)previous);
        Put(form, "targetDisplay", "fixture-previous-display");
        ContextMenuStrip menu = Open(form);
        bool found = false;
        Exception callbackFailure = null;
        using (System.Windows.Forms.Timer closePicker = new System.Windows.Forms.Timer { Interval = 1 })
        {
            closePicker.Tick += delegate
            {
                RegionPicker picker = null;
                foreach (Form open in Application.OpenForms) if (open is RegionPicker) { picker = (RegionPicker)open; break; }
                if (picker == null) return;
                closePicker.Stop(); found = true;
                try
                {
                    picker.Opacity = 0;
                    if (accept)
                    {
                        SendMessage(picker.Handle, 0x201, new IntPtr(1), new IntPtr((40 << 16) | 30));
                        SendMessage(picker.Handle, 0x200, new IntPtr(1), new IntPtr((100 << 16) | 150));
                        SendMessage(picker.Handle, 0x202, IntPtr.Zero, new IntPtr((100 << 16) | 150));
                    }
                    else SendMessage(picker.Handle, 0x100, new IntPtr(27), IntPtr.Zero);
                    if (!picker.IsDisposed && picker.DialogResult == DialogResult.None)
                        throw new InvalidOperationException("The generated picker input did not complete its modal result.");
                }
                catch (Exception error)
                {
                    callbackFailure = error;
                    if (!picker.IsDisposed) { picker.DialogResult = DialogResult.Cancel; picker.Close(); }
                }
            };
            closePicker.Start();
            NativeClick(menu, menu.Items[menu.Items.Count - 1]);
            Check(!menu.Visible && !menu.IsDisposed && Field<bool>(form, "captureTargetActionPending") && !Field<bool>(form, "selectingArea"),
                "Draw click closes native menu before dispatching the modal action");
            // The real production BeginInvoke opens its real modal picker. Only
            // targeted messages to that app-owned picker supply synthetic input.
            Pump();
            closePicker.Stop();
            if (callbackFailure != null) throw callbackFailure;
            Check(found, "Draw action opens and completes the real picker");
        }
        Rectangle? chosen = Field<Rectangle?>(form, "selectedRegion");
        if (accept)
        {
            Check(chosen.HasValue && chosen.Value.Width == 120 && chosen.Value.Height == 60 && Field<string>(form, "targetDisplay") == null,
                "A generated drag commits its 120 by 60 capture rectangle and clears the display target");
            Check(Field<Label>(form, "regionLabel").Text.Contains("120") && Field<Label>(form, "regionLabel").Text.Contains("60"),
                "Accepted area updates the dashboard region label");
        }
        else Check(chosen == previous && Field<string>(form, "targetDisplay") == "fixture-previous-display",
            "Escape cancels area drawing and retains the previous target");
        Check(!Field<bool>(form, "selectingArea") && !Field<bool>(form, "captureTargetActionPending") && !menu.IsDisposed,
            "Completing the modal picker releases selection and queue state while retaining the menu");
        form.Hide();
    }
    static bool DisposedFailure(Exception error)
    {
        if (error is ObjectDisposedException && error.Message.Contains("ContextMenuStrip")) return true;
        AggregateException many = error as AggregateException;
        if (many != null) foreach (Exception nested in many.InnerExceptions) if (DisposedFailure(nested)) return true;
        return error.InnerException != null && DisposedFailure(error.InnerException);
    }
    static void DisposeDuringDrawing()
    {
        using (MainForm form = new MainForm())
        using (System.Windows.Forms.Timer cancel = new System.Windows.Forms.Timer { Interval = 1 })
        {
            Isolate(form);
            ContextMenuStrip menu = Open(form);
            bool pickerSeen = false;
            bool ownerClosedPicker = false;
            cancel.Tick += delegate
            {
                RegionPicker picker = null;
                foreach (Form open in Application.OpenForms) if (open is RegionPicker) { picker = (RegionPicker)open; break; }
                if (picker == null) return;
                cancel.Stop(); pickerSeen = true;
                picker.Opacity = 0;
                form.Dispose();
                ownerClosedPicker = picker.IsDisposed || !picker.Visible;
                // Fail safely instead of leaving a regression's modal window open.
                if (!ownerClosedPicker) { picker.DialogResult = DialogResult.Cancel; picker.Close(); }
            };
            cancel.Start();
            NativeClick(menu, menu.Items[menu.Items.Count - 1]);
            Pump();
            Check(pickerSeen && ownerClosedPicker && form.IsDisposed && menu.IsDisposed,
                "Disposing the dashboard during area drawing closes safely without resurrecting its owner");
        }
    }
    [STAThread] static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += delegate(object sender, ThreadExceptionEventArgs e) { failures.Add(e.Exception); };
        bool baseline = args.Length != 0 && args[0] == "--expect-baseline-failure";
        bool shutdown = args.Length != 0 && args[0] == "--owner-dispose-only";
        string directory = Path.GetFullPath(args.Length == 0 || baseline || shutdown ? Path.GetTempPath() : args[0]);
        Directory.CreateDirectory(directory);
        try
        {
            if (shutdown)
            {
                DisposeDuringDrawing();
                Console.WriteLine(passed + " capture owner shutdown checks passed.");
                return 0;
            }
            using (MainForm form = new MainForm())
            {
                Isolate(form);
                if (!baseline) CheckAppearance(form, directory);
                Put(form, "selectedRegion", (Rectangle?)new Rectangle(10, 10, 100, 100));
                ContextMenuStrip menu = Open(form);
                NativeClick(menu, menu.Items[0]);
                if (!baseline)
                    Check(Field<Rectangle?>(form, "selectedRegion").HasValue && Field<bool>(form, "captureTargetActionPending"),
                        "Screen selection is deferred until native menu dispatch returns");
                Pump();
                if (baseline) throw new InvalidOperationException("Baseline did not reproduce the disposed menu exception.");
                Check(!menu.Visible && !menu.IsDisposed, "Primary display click dismisses the popup without disposing it in native dispatch");
                Check(!Field<Rectangle?>(form, "selectedRegion").HasValue && Field<string>(form, "targetDisplay") == null,
                    "Primary display selection clears a previously drawn area");
                List<Screen> secondary = new List<Screen>();
                foreach (Screen display in Screen.AllScreens) if (!display.Primary) secondary.Add(display);
                menu = Open(form);
                Check(menu.Items.Count == secondary.Count + 3, "The menu reflects currently connected non-primary displays");
                menu.Close(); Pump();
                foreach (Screen display in secondary)
                {
                    menu = Open(form);
                    int index = secondary.IndexOf(display) + 1;
                    NativeClick(menu, menu.Items[index]); Pump();
                    Check(Field<string>(form, "targetDisplay") == display.DeviceName && !Field<Rectangle?>(form, "selectedRegion").HasValue,
                        "A connected secondary display selection retains its exact device identity");
                }
                Rectangle? beforeDismissal = Field<Rectangle?>(form, "selectedRegion");
                string beforeDisplay = Field<string>(form, "targetDisplay");
                menu = Open(form);
                Message escape = Message.Create(menu.Handle, 0x100, new IntPtr(27), IntPtr.Zero);
                if (!menu.PreProcessMessage(ref escape)) SendMessage(menu.Handle, escape.Msg, escape.WParam, escape.LParam);
                Pump();
                Check(!menu.Visible && !menu.IsDisposed && Field<Rectangle?>(form, "selectedRegion") == beforeDismissal && Field<string>(form, "targetDisplay") == beforeDisplay,
                    "Escape dismisses the popup without changing or disposing its target");
                ToolStripItem previousItem = menu.Items[0];
                for (int cycle = 0; cycle < 12; cycle++)
                {
                    bool released = false;
                    previousItem.Disposed += delegate { released = true; };
                    ContextMenuStrip reopened = Open(form);
                    Check(Object.ReferenceEquals(menu, reopened) && released && !menu.Items.Contains(previousItem),
                        "Reopening reuses the owner menu and disposes detached old items");
                    previousItem = menu.Items[0];
                    menu.Close(); Pump();
                }
                Draw(form, false);
                Draw(form, true);
                menu = Open(form); NativeClick(menu, menu.Items[0]); Pump();
                Check(!Field<Rectangle?>(form, "selectedRegion").HasValue, "A screen can be selected again after drawing an area");
                bool queued = false, duplicate = false;
                Call(form, "QueueCaptureTarget", new Action(delegate { queued = true; }));
                Call(form, "QueueCaptureTarget", new Action(delegate { duplicate = true; }));
                Pump();
                Check(queued && !duplicate && !Field<bool>(form, "captureTargetActionPending"),
                    "A pending action prevents duplicate queued selection and releases its guard");
                bool closingAction = false;
                Call(form, "QueueCaptureTarget", new Action(delegate { closingAction = true; }));
                Put(form, "closing", true); Pump();
                Check(!closingAction && !Field<bool>(form, "captureTargetActionPending"), "Closing an owner cancels its queued action");
                Put(form, "closing", false);
                Check(Field<object>(form, "worker") == null && !Field<bool>(form, "screenWanted"),
                    "The menu fixture starts no worker or screen capture");
                bool disposedAction = false;
                Call(form, "QueueCaptureTarget", new Action(delegate { disposedAction = true; }));
                form.Dispose(); Pump();
                Check(menu.IsDisposed && !disposedAction, "Owner disposal releases its menu and prevents later queued work");
            }
            // Native menu/modal thread state is process-global. A separate
            // fixture represents app shutdown without reusing a stopped owner's
            // menu manager or starting any production helper.
            var start = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location, "--owner-dispose-only")
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            using (Process child = Process.Start(start))
            {
                var stdout = child.StandardOutput.ReadToEndAsync();
                var stderr = child.StandardError.ReadToEndAsync();
                if (!child.WaitForExit(15000)) { child.Kill(); throw new InvalidOperationException("Owner shutdown fixture timed out."); }
                Console.Write(stdout.GetAwaiter().GetResult()); Console.Error.Write(stderr.GetAwaiter().GetResult());
                Check(child.ExitCode == 0, "Fresh-process owner disposal during a modal draw exits without a UI exception");
            }
            Console.WriteLine(passed + " capture target menu checks passed.");
            return 0;
        }
        catch (Exception error)
        {
            if (baseline && DisposedFailure(error))
            {
                Console.WriteLine("PASS reproduced the original ObjectDisposedException for ContextMenuStrip through native item dismissal.");
                return 0;
            }
            Console.Error.WriteLine(error); return 1;
        }
    }
}
