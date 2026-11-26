using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
using LiveTranslate;

internal static class Patch081ControlsCheck
{
    const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;
    static int count;
    static T Get<T>(object owner, string name) { return (T)owner.GetType().GetField(name, Private).GetValue(owner); }
    static void Put(object owner, string name, object value) { owner.GetType().GetField(name, Private).SetValue(owner, value); }
    static object Call(object owner, string name, params object[] args) { return owner.GetType().GetMethod(name, Private).Invoke(owner, args); }
    static void Check(bool value, string text) { if (!value) throw new Exception(text); count++; Console.WriteLine("PASS " + text); }
    static void Isolate(Form form)
    {
        var events = (EventHandlerList)typeof(Component).GetProperty("Events", Private).GetValue(form, null);
        foreach (string name in new[] { "EVENT_LOAD", "EVENT_SHOWN" })
        {
            object key = typeof(Form).GetField(name, Static).GetValue(null);
            if (events[key] != null) events.RemoveHandler(key, events[key]);
        }
        form.StartPosition = FormStartPosition.Manual;
        form.Location = new Point(SystemInformation.VirtualScreen.Right + 200, 0); form.ShowInTaskbar = false;
    }
    static void Opacity(string output)
    {
        foreach (int opacity in new[] { 0, 50, 100 })
        {
            var snapshot = new NativeVrCaptionSnapshot { Status = "Paused", Translation = "Readable captions stay opaque.", BackgroundOpacity = opacity };
            using (Bitmap image = NativeVrCaptionPainter.Render(snapshot, 0))
            {
                Check(Math.Abs(image.GetPixel(600, 460).A - Math.Round(opacity * 255.0 / 100)) <= 1, "Background alpha follows " + opacity + "%");
                int opaqueText = 0;
                for (int y = 185; y < 245; y++) for (int x = 40; x < 850; x++)
                { Color pixel = image.GetPixel(x, y); if (pixel.A == 255 && pixel.R >= 245 && pixel.G >= 245 && pixel.B >= 245) opaqueText++; }
                Check(opaqueText > 100, "Caption lettering remains opaque with " + opacity + "% background");
                image.Save(Path.Combine(output, "opacity-" + opacity + ".png"));
            }
            var copied = snapshot.Copy(); Check(copied.SameAs(snapshot), "Opacity survives snapshot copying");
            copied.BackgroundOpacity = opacity == 0 ? 100 : 0;
            Check(!copied.SameAs(snapshot), "Opacity change invalidates the unchanged-image cache");
        }
        using (var slider = new OpacitySlider())
        {
            Call(slider, "OnKeyDown", new KeyEventArgs(Keys.Home)); Check(slider.Value == 0, "Home selects transparent background");
            Call(slider, "OnKeyDown", new KeyEventArgs(Keys.End)); Check(slider.Value == 100, "End selects opaque background");
            Call(slider, "OnKeyDown", new KeyEventArgs(Keys.PageDown)); Check(slider.Value == 90, "Keyboard page step changes opacity");
            slider.AccessibilityObject.Value = "50%";
            Check(slider.Value == 50 && slider.AccessibilityObject.Role == AccessibleRole.Slider, "Accessible slider value changes opacity");
            slider.Value = -20; Check(slider.Value == 0, "Slider bounds reject negative opacity");
            slider.Value = 150; Check(slider.Value == 100, "Slider bounds reject opacity above 100");
        }
    }
    static void Profiles(string output)
    {
        string path = Path.Combine(output, "profile-test.json");
        File.WriteAllText(path, "{\"width\":1.1,\"distance\":2.2,\"height\":-0.3}");
        var profiles = VrConnectionProfiles.Read(path);
        Check(profiles.Get("steamvr").width == 1.1M && profiles.Get("steamvr").distance == 2.2M, "0.8.0 placement migrates without losing dimensions");
        profiles.Selected = "virtualdesktop"; profiles.Get("virtualdesktop").width = .7M; profiles.Get("virtualdesktop").opacity = 25;
        profiles.Write(path); profiles = VrConnectionProfiles.Read(path);
        Check(profiles.Selected == "virtualdesktop" && profiles.Get("virtualdesktop").opacity == 25, "Connection and opacity persist across restart");
        Check(profiles.Get("steamvr").width == 1.1M && profiles.Get("virtualdesktop").width == .7M, "Connections retain separate layouts");
        Check(!File.Exists(path + ".tmp"), "Atomic preference write leaves no pending file");
        File.WriteAllText(path, "{\"connection\":\"unknown\",\"profiles\":{\"steamvr\":{\"opacity\":900,\"width\":99}}}");
        profiles = VrConnectionProfiles.Read(path);
        Check(profiles.Selected == "steamvr" && profiles.Get("steamvr").opacity == 100 && profiles.Get("steamvr").width == 1.4M, "Invalid saved profile values remain bounded");
        File.WriteAllText(path, "broken json"); Check(VrConnectionProfiles.Read(path).Get("steamvr").opacity == 95, "Damaged preferences recover to safe defaults");
    }
    static Dictionary<string, object> Signal(string session, int endpoint, int level)
    {
        return new Dictionary<string, object> { { "type", "audio_diagnostic" }, { "channel", "audio" }, { "session_id", session },
            { "stage", "signal" }, { "source", "pc" }, { "endpoint", endpoint }, { "level", level }, { "message", "Measured fixture input" } };
    }
    static void App()
    {
        using (var app = new MainForm())
        {
            Isolate(app); Put(app, "screenArmed", false);
            Form settings = Get<Form>(app, "settingsForm"); Isolate(settings);
            app.Show(); Application.DoEvents();
            Check(Get<object>(app, "worker") == null && Get<NativeVrOverlay>(app, "nativeVrOverlay") == null, "New controls start no input capture or VR runtime");
            var connections = Get<ComboBox>(app, "nativeVrConnection");
            connections.SelectedIndex = 0;
            Get<OpacitySlider>(app, "nativeVrOpacity").Value = 95;
            connections.SelectedIndex = 1; Get<OpacitySlider>(app, "nativeVrOpacity").Value = 30;
            Get<NumericUpDown>(app, "nativeVrWidth").Value = .7M;
            connections.SelectedIndex = 0;
            Check(Get<OpacitySlider>(app, "nativeVrOpacity").Value == 95, "Profile switching restores the outgoing connection's opacity");
            connections.SelectedIndex = 1;
            Check(Get<OpacitySlider>(app, "nativeVrOpacity").Value == 30 && Get<NumericUpDown>(app, "nativeVrWidth").Value == .7M, "Returning to Virtual Desktop restores its saved layout");
            connections.SelectedIndex = 4;
            Check(!Get<Button>(app, "nativeVrStart").Enabled, "Unsupported OpenXR profile cannot start the SteamVR backend");
            Call(app, "StartNativeVrCaptions");
            Check(Get<NativeVrOverlay>(app, "nativeVrOverlay") == null, "Unsupported connection reports a limitation without starting a runtime");
            settings.Hide(); connections.SelectedIndex = 0;
            Put(app, "audioWanted", true); Put(app, "audioSession", "current-audio");
            Call(app, "HandleMessage", Signal("current-audio", 1, 75));
            Check(Get<AudioSignalMeter>(app, "audioSignalMeter").Level == 75, "Measured input drives the level display");
            Call(app, "HandleMessage", Signal("current-audio", 2, 0));
            Check(Get<AudioSignalMeter>(app, "audioSignalMeter").Level == 75, "A silent second endpoint cannot erase active playback");
            Call(app, "HandleMessage", Signal("old-session", 1, 99));
            Check(Get<AudioSignalMeter>(app, "audioSignalMeter").Level == 75, "A stale audio session cannot overwrite the meter");
            Call(app, "HandleMessage", new Dictionary<string, object> { { "type", "audio_diagnostic" }, { "channel", "audio" },
                { "session_id", "current-audio" }, { "stage", "recognition" }, { "language", "ja" }, { "probability", .91 },
                { "recognized", "窓を開けてください。" }, { "message", "Source not confirmed; diagnostic only." } });
            Check(Get<TextBox>(app, "audioRecognizedText").Text == "窓を開けてください。" && Get<Label>(app, "audioDecisionLabel").Text.Contains("91%"), "Recognized source and language confidence are inspectable separately");
            Check(Get<IList>(app, "history").Count == 0, "Recognition diagnostics never fabricate captions");
            Call(app, "StopAudio");
            Check(Get<AudioSignalMeter>(app, "audioSignalMeter").Level == 0 && Get<TextBox>(app, "audioRecognizedText").Text.Length == 0, "Stopping clears measured input and old recognition details");
        }
    }
    [STAThread] static int Main(string[] args)
    {
        string output = Path.GetFullPath(args[0]); Directory.CreateDirectory(output);
        string prefs = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "config", "vr-overlay.json");
        byte[] original = File.Exists(prefs) ? File.ReadAllBytes(prefs) : null;
        try { Application.EnableVisualStyles(); Opacity(output); Profiles(output); App(); Console.WriteLine(count + " patch 0.8.1 controls checks passed."); return 0; }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally { if (original != null) File.WriteAllBytes(prefs, original); else if (File.Exists(prefs)) File.Delete(prefs); }
    }
}
