using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("LiveTranslate installation helper")]
[assembly: AssemblyProduct("LiveTranslate")]

namespace LiveTranslate.Setup
{
    internal static class InstalledLauncher
    {
        [STAThread]
        private static int Main(string[] args)
        {
            try
            {
                DirectoryInfo support = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory);
                if (support.Parent == null || !support.Name.Equals(".lt-setup", StringComparison.OrdinalIgnoreCase))
                    throw new IOException("Run LiveTranslate setup to repair this installation.");
                if (args.Length == 1 && args[0] == "--uninstall")
                    StartUninstall(support);
                else if (args.Length == 0)
                {
                    string root = support.Parent.FullName;
                    using (Process child = Process.Start(new ProcessStartInfo(Path.Combine(root, "LiveTranslate.exe")) {
                        WorkingDirectory = root, UseShellExecute = false
                    })) { }
                }
                else throw new ArgumentException("Open LiveTranslate from your Start menu.");
                return 0;
            }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, "LiveTranslate", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }

        private static void StartUninstall(DirectoryInfo support)
        {
            string script = Path.Combine(support.FullName, "Setup.ps1");
            if (!File.Exists(script)) throw new FileNotFoundException("Run setup to restore the missing uninstaller.");
            const string command = "$ErrorActionPreference='Stop'; try { " +
                "Wait-Process -Id ([int]$env:LT_UNINSTALL_PARENT_PID) -ErrorAction SilentlyContinue; " +
                "& $env:LT_INSTALLED_UNINSTALL_SCRIPT -Uninstall " +
                "} catch { Add-Type -AssemblyName System.Windows.Forms; " +
                "[void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message,'LiveTranslate uninstall','OK','Error'); exit 1 }";
            var start = new ProcessStartInfo {
                FileName = Path.Combine(Environment.SystemDirectory, @"WindowsPowerShell\v1.0\powershell.exe"),
                WorkingDirectory = Environment.SystemDirectory,
                Arguments = "-NoLogo -NoProfile -STA -NonInteractive -ExecutionPolicy RemoteSigned -Command \"" + command + "\"",
                UseShellExecute = false, CreateNoWindow = true
            };
            start.EnvironmentVariables.Remove("PSModulePath");
            start.EnvironmentVariables["LT_INSTALLED_UNINSTALL_SCRIPT"] = script;
            using (Process parent = Process.GetCurrentProcess())
                start.EnvironmentVariables["LT_UNINSTALL_PARENT_PID"] = parent.Id.ToString(CultureInfo.InvariantCulture);
            using (Process child = Process.Start(start)) { }
        }
    }
}
