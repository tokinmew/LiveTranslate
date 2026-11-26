using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace LiveTranslate
{
    internal sealed class ApplicationCaptureTarget
    {
        internal IntPtr Handle;
        internal uint ProcessId;
        internal string Title;
        internal ApplicationCaptureTarget(IntPtr handle, uint processId, string title)
        { Handle = handle; ProcessId = processId; Title = title; }
    }

    internal static class ApplicationCapture
    {
        private delegate bool EnumWindow(IntPtr handle, IntPtr parameter);
        [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindow callback, IntPtr parameter);
        [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr handle);
        [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr handle);
        [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr handle);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr handle, StringBuilder title, int size);
        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr handle, out uint process);
        [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr handle, out NativeRect rect);
        [DllImport("user32.dll")] private static extern bool ClientToScreen(IntPtr handle, ref Point point);
        [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
        [StructLayout(LayoutKind.Sequential)] private struct NativeRect { internal int Left, Top, Right, Bottom; }

        internal static List<ApplicationCaptureTarget> Windows()
        {
            List<ApplicationCaptureTarget> targets = new List<ApplicationCaptureTarget>();
            uint own = (uint)Process.GetCurrentProcess().Id;
            EnumWindow collect = delegate(IntPtr hwnd, IntPtr unused)
            {
                uint process;
                if (!IsWindowVisible(hwnd) || GetWindowThreadProcessId(hwnd, out process) == 0 || process == own) return true;
                StringBuilder title = new StringBuilder(256);
                if (GetWindowText(hwnd, title, title.Capacity) <= 0 || String.IsNullOrWhiteSpace(title.ToString())) return true;
                targets.Add(new ApplicationCaptureTarget(hwnd, process, title.ToString()));
                return true;
            };
            EnumWindows(collect, IntPtr.Zero);
            targets.Sort(delegate(ApplicationCaptureTarget a, ApplicationCaptureTarget b)
            {
                bool av = a.Title.IndexOf("VRChat", StringComparison.OrdinalIgnoreCase) >= 0;
                bool bv = b.Title.IndexOf("VRChat", StringComparison.OrdinalIgnoreCase) >= 0;
                if (av != bv) return av ? -1 : 1;
                return StringComparer.CurrentCultureIgnoreCase.Compare(a.Title, b.Title);
            });
            return targets;
        }

        internal static Rectangle Bounds(ApplicationCaptureTarget target)
        {
            uint process;
            NativeRect rect;
            Point origin = Point.Empty;
            if (target == null || !IsWindow(target.Handle) || IsIconic(target.Handle) ||
                GetWindowThreadProcessId(target.Handle, out process) == 0 || process != target.ProcessId ||
                !GetClientRect(target.Handle, out rect) || !ClientToScreen(target.Handle, ref origin)) return Rectangle.Empty;
            int width = rect.Right - rect.Left, height = rect.Bottom - rect.Top;
            return width >= 5 && height >= 5 && (long)width * height <= 40000000 ? new Rectangle(origin.X, origin.Y, width, height) : Rectangle.Empty;
        }

        internal static bool IsForeground(ApplicationCaptureTarget target)
        { return target != null && GetForegroundWindow() == target.Handle; }
    }

    internal sealed class CapturePreviewWindow : Form
    {
        private const string CaptureMarker = "LiveTranslate.CapturePreview";
        [DllImport("user32.dll", EntryPoint = "SetPropW", CharSet = CharSet.Unicode)]
        private static extern bool SetMarker(IntPtr handle, string name, IntPtr value);
        [DllImport("user32.dll", EntryPoint = "RemovePropW", CharSet = CharSet.Unicode)]
        private static extern IntPtr RemoveMarker(IntPtr handle, string name);
        protected override void OnHandleCreated(EventArgs args)
        {
            base.OnHandleCreated(args);
            SetMarker(Handle, CaptureMarker, new IntPtr(1));
            // The watcher discovers this marker even when it started before
            // the preview. Keep the preview capturable for screenshots and
            // support; only the OCR input masks this app-owned rectangle.
        }
        protected override void OnHandleDestroyed(EventArgs args)
        {
            if (IsHandleCreated) RemoveMarker(Handle, CaptureMarker);
            base.OnHandleDestroyed(args);
        }
    }

    internal sealed partial class MainForm
    {
        private ApplicationCaptureTarget captureApplication;
        private Form capturePreview;
        private int capturePreviewRequest;
        private readonly Dictionary<string, string> lastCaptureErrors = new Dictionary<string, string>();

        private void ReportCaptureError(string channel, string message)
        {
            if (channel != "screen" && channel != "screen_once" && channel != "audio") return;
            string previous;
            if (!lastCaptureErrors.TryGetValue(channel, out previous) || previous != message)
                Append("CAPTURE", message);
            lastCaptureErrors[channel] = message;
            SetStatus(message);
        }

        private void ClearCaptureError(string channel)
        {
            lastCaptureErrors.Remove(channel);
        }

        private void InvalidateCapturePreview()
        {
            capturePreviewRequest = 0;
            if (capturePreview != null && !capturePreview.IsDisposed) capturePreview.Close();
        }

        private void SelectApplication(ApplicationCaptureTarget target)
        {
            InvalidateCapturePreview();
            captureApplication = target;
            selectedRegion = null;
            targetDisplay = null;
            UpdateRegionLabel();
            CancelReadOnce();
            ReconfigureScreen();
            SetStatus("Capturing only the selected application. Keep it restored and rendering. Preview captured view to verify the source.");
        }

        private void AddApplicationCaptureItems(ContextMenuStrip menu)
        {
            ToolStripMenuItem applications = new ToolStripMenuItem("Application window (single monitor)");
            foreach (ApplicationCaptureTarget target in ApplicationCapture.Windows())
            {
                ApplicationCaptureTarget chosen = target;
                ToolStripMenuItem item = new ToolStripMenuItem(target.Title, null,
                    delegate { QueueCaptureTarget(delegate { SelectApplication(chosen); }); });
                item.Checked = captureApplication != null && captureApplication.Handle == target.Handle && captureApplication.ProcessId == target.ProcessId;
                applications.DropDownItems.Add(item);
            }
            if (applications.DropDownItems.Count == 0)
                applications.DropDownItems.Add(new ToolStripMenuItem("Open VRChat or another application first") { Enabled = false });
            applications.DropDown.Renderer = menu.Renderer;
            applications.DropDown.BackColor = menu.BackColor;
            applications.DropDown.ForeColor = menu.ForeColor;
            menu.Items.Add(applications);
            menu.Items.Add("Preview captured view…", null, delegate { QueueCaptureTarget(RequestCapturePreview); });
        }

        private void RequestCapturePreview()
        {
            if (!connected) { SetStatus("Wait for the local engine before previewing the captured view."); return; }
            if (capturePreview != null && !capturePreview.IsDisposed) { capturePreview.BringToFront(); return; }
            if (capturePreviewRequest != 0) { SetStatus("The captured view preview is still being prepared."); return; }
            if (CaptureBounds().IsEmpty) { SetStatus("Restore the selected application or choose a display first."); return; }
            SetStatus("Preparing a preview of the selected capture source…");
            Dictionary<string, object> args = ScreenArguments("");
            if (Send("preview_screen", args)) capturePreviewRequest = Convert.ToInt32(args["id"]);
        }

        private void FinishCapturePreview(int requestId, Dictionary<string, object> message)
        {
            // A queued frame belongs to the source chosen at request time.
            // Changing source invalidates the ID; late frames cannot appear as
            // a preview of the newly selected application/display.
            if (capturePreviewRequest == 0 || requestId != capturePreviewRequest) return;
            capturePreviewRequest = 0;
            if (Value(message, "type") == "screen_preview") ShowCapturePreview(message);
            else SetStatus("Capture preview failed: " + Value(message, "message"));
        }

        private void ShowCapturePreview(Dictionary<string, object> message)
        {
            if (closing || IsDisposed) return;
            try
            {
                byte[] encoded = Convert.FromBase64String(Value(message, "image"));
                if (encoded.Length > 2000000) throw new InvalidDataException("The capture preview is too large.");
                Image frame;
                using (MemoryStream stream = new MemoryStream(encoded))
                using (Image decoded = Image.FromStream(stream)) frame = new Bitmap(decoded);
                if (capturePreview != null && !capturePreview.IsDisposed) capturePreview.Close();
                Form preview = new CapturePreviewWindow { Text = "Captured view · LiveTranslate", StartPosition = FormStartPosition.CenterParent,
                    Size = new Size(980, 660), MinimumSize = new Size(560, 390), BackColor = background, ForeColor = ink, Font = Font };
                capturePreview = preview;
                PictureBox picture = new PictureBox { Dock = DockStyle.Fill, Image = frame, SizeMode = PictureBoxSizeMode.Zoom,
                    BackColor = field, AccessibleName = "Current captured view" };
                var tabs = new ThemedTabControl { Dock = DockStyle.Fill, AccessibleName = "Capture preview sections" };
                var imageTab = new TabPage("Captured image") { BackColor = field };
                var detailTab = new TabPage("Recognition details") { BackColor = field, Padding = new Padding(8) };
                imageTab.Controls.Add(picture);
                var details = new ThemedTextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true,
                    ScrollBars = ScrollBars.Vertical, WordWrap = true, Text = CaptureDiagnosticText(message),
                    BackColor = field, ForeColor = ink, BorderStyle = BorderStyle.None,
                    Name = "CaptureRecognitionDetails", AccessibleName = "Capture and unverified OCR diagnostics" };
                detailTab.Controls.Add(details);
                tabs.TabPages.Add(imageTab); tabs.TabPages.Add(detailTab);
                Label explanation = new Label { Dock = DockStyle.Bottom, Height = 128, Padding = new Padding(14), ForeColor = muted,
                    Text = "This is the image supplied to screen recognition (" + Value(message, "width") + " × " + Value(message, "height") + ").\n" +
                    (Value(message, "source") == "application" ? "Only the selected application is captured. Keep it restored and rendering. This is its PC view, not a direct headset feed." :
                    "Manual capture briefly clears overlapping LiveTranslate windows. Watching keeps the dashboard visible; minimize it or choose Application window if it covers the text.") +
                    "\nOne frame only; reopen to refresh. Recognition details shows unverified OCR. No screenshot is saved." };
                preview.Controls.Add(tabs);
                preview.Controls.Add(explanation);
                preview.FormClosed += delegate { picture.Image = null; frame.Dispose(); if (capturePreview == preview) capturePreview = null; };
                WindowTheme.Apply(preview);
                preview.Show(this);
                SetStatus("Captured view opened. Check that the expected foreign text is visible and large enough.");
            }
            catch (Exception e) { SetStatus("Could not show capture preview: " + e.GetBaseException().Message); }
        }

        private static string CaptureDiagnosticText(Dictionary<string, object> message)
        {
            object value;
            var details = message.TryGetValue("diagnostics", out value) ? value as Dictionary<string, object> : null;
            details = details ?? new Dictionary<string, object>();
            return "Capture: " + Value(message, "source") + " · " + Value(message, "width") + " × " + Value(message, "height") +
                "\r\nArea covered by LiveTranslate: " + (Value(details, "masked_percent") == "" ? "unknown" : Value(details, "masked_percent") + "%") +
                "\r\nSelected source: " + Value(details, "selected_language") + " · OCR reader: " + Value(details, "ocr_language") +
                "\r\n\r\nUnverified OCR — diagnostic only, may contain invented or misread characters:\r\n" +
                (Value(details, "raw_ocr") == "" ? "(No raw text returned.)" : Value(details, "raw_ocr")) +
                "\r\n\r\nAccepted source after recognition safeguards:\r\n" +
                (Value(details, "accepted_ocr") == "" ? "(No supported foreign text confirmed.)" : Value(details, "accepted_ocr")) +
                (Value(details, "recognition_error") == "" ? "" : "\r\n\r\nRecognition error:\r\n" + Value(details, "recognition_error")) +
                "\r\n\r\nThese diagnostic readings are not added to captions or read aloud.";
        }
    }
}
