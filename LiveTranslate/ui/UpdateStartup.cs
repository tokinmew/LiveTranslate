using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;

// Called before the application creates its dashboard or starts the Python worker.
internal static class UpdateStartup
{
    private static FileStream lifetimeGuard;

    internal static bool HandOffIfBusy()
    {
        string root = Path.GetDirectoryName(Application.ExecutablePath);
        string state = Path.Combine(root, ".livetranslate-update");
        string journal = Path.Combine(state, "transaction.json");
        string gate = Path.Combine(state, "run.lock");
        try
        {
            Directory.CreateDirectory(state);
            for (int attempt = 0; attempt < 8; attempt++)
            {
                if (File.Exists(journal)) return HandOff(root, state);
                try
                {
                    // All running dashboards share read access. The update helper
                    // requests an exclusive handle before changing any program files.
                    lifetimeGuard = new FileStream(gate, FileMode.OpenOrCreate,
                        FileAccess.Read, FileShare.Read);
                    if (!File.Exists(journal)) return false;
                    lifetimeGuard.Dispose();
                    lifetimeGuard = null;
                    return HandOff(root, state);
                }
                catch (IOException ex)
                {
                    int code = ex.HResult & 0xffff;
                    if (code != 32 && code != 33) throw;
                    Thread.Sleep(80);
                }
            }
            if (File.Exists(journal)) return HandOff(root, state);
            MessageBox.Show("Another update is finishing. Open LiveTranslate again in a moment.",
                "LiveTranslate update", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return true;
        }
        catch (UnauthorizedAccessException)
        {
            // A read-only install can still translate; the download/apply preflight
            // reports the directory permissions when the user requests an update.
            return File.Exists(journal) && HandOff(root, state);
        }
        catch (IOException ex)
        {
            if (File.Exists(journal)) return HandOff(root, state);
            MessageBox.Show("Windows could not open the application update lock.\r\n\r\n" + ex.Message,
                "LiveTranslate update", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return true;
        }
    }

    private static bool HandOff(string root, string state)
    {
        try
        {
            string python = Path.Combine(root, @"runtime\python.exe");
            string helper = Path.Combine(state, "recovery.py");
            if (!File.Exists(helper)) helper = Path.Combine(root, @"backend\update_install.py");
            if (!File.Exists(python) || !File.Exists(helper))
                throw new FileNotFoundException("Run the updater setup again to finish recovery.");
            var info = new ProcessStartInfo(python,
                "-I -B " + Quote(helper) + " recover --root " + Quote(root) + " --parent 0");
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            // Recovery waits for this transient startup process to end. If the
            // original installer is still active, its own lock suppresses a second recovery.
            using (Process started = Process.Start(info)) { }
        }
        catch (Exception ex)
        {
            MessageBox.Show("An interrupted update needs recovery.\r\n\r\n" + ex.Message,
                "LiveTranslate update", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        return true;
    }

    private static string Quote(string value)
    {
        // Windows paths cannot contain double quotes. An absolute drive-root path
        // can end in backslashes, which must be doubled before the closing quote.
        int end = value.Length;
        while (end > 0 && value[end - 1] == '\\') end--;
        return "\"" + value + new string('\\', value.Length - end) + "\"";
    }
}
