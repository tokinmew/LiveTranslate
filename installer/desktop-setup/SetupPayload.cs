using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Windows.Forms;

[assembly: AssemblyTitle("LiveTranslate Setup")]
[assembly: AssemblyProduct("LiveTranslate")]
[assembly: AssemblyDescription("Per-user Windows installer for LiveTranslate")]

namespace LiveTranslate.Setup
{
    internal static class SetupPayload
    {
        private const string Package = "Portable.zip";
        private static readonly string[] PayloadFiles = { "Setup.ps1", "files.json", Package, "LiveTranslate.Launcher.exe" };

        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupWindow());
        }

        private static void CheckHash(Stream data, string expected)
        {
            using (var sha = SHA256.Create())
            {
                string actual = BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "");
                if (!String.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("The installer failed its integrity check. Please download a fresh copy.");
            }
        }

        internal static void Extract(string staging)
        {
            foreach (string name in PayloadFiles)
            {
                using (var output = new FileStream(Path.Combine(staging, name), FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    if (name == Package) RestorePortable(output);
                    else using (Stream input = Resource(name)) input.CopyTo(output);
                }
            }
        }

        private static Stream Resource(string name)
        {
            var stream = typeof(SetupPayload).Assembly.GetManifestResourceStream(name);
            if (stream == null) throw new InvalidDataException("Missing installer resource: " + name);
            return stream;
        }

        [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
        [DllImport("cabinet.dll")]
        private static extern bool CreateDecompressor(uint algorithm, IntPtr allocation, out IntPtr decoder);

        [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
        [DllImport("cabinet.dll")]
        private static extern bool Decompress(IntPtr decoder, byte[] input, UIntPtr inputSize,
            [Out] byte[] output, UIntPtr outputSize, out UIntPtr actual);

        [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
        [DllImport("cabinet.dll")]
        private static extern bool CloseDecompressor(IntPtr decoder);

        private static void RestorePortable(Stream destination)
        {
            using (Stream prefix = Resource("Portable.prefix")) prefix.CopyTo(destination);
            using (Stream suffix = Resource("Portable.suffix"))
            using (var reader = new BinaryReader(suffix))
            {
                byte[] compressed = reader.ReadBytes(checked((int)suffix.Length));
                byte[] restored = new byte[GeneratedPins.SuffixSize];
                IntPtr decoder;
                if (!CreateDecompressor(5, IntPtr.Zero, out decoder))
                    throw new IOException("Windows could not open its built-in installer decompressor.");
                try
                {
                    UIntPtr actual;
                    if (!Decompress(decoder, compressed, (UIntPtr)(uint)compressed.Length, restored,
                            (UIntPtr)(uint)restored.Length, out actual) || actual.ToUInt64() != (ulong)restored.Length)
                        throw new InvalidDataException("The installer is incomplete. Download a fresh copy.");
                    destination.Write(restored, 0, restored.Length);
                }
                finally { CloseDecompressor(decoder); }
            }
        }

        internal static void InstallFrom(string staging, string installBase, string startMenu)
        {
            if ((installBase == null) != (startMenu == null)) throw new ArgumentException("Both installation folders must be provided together.");
            string defaultBase = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "LiveTranslate");
            string defaultMenu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "LiveTranslate");
            string script = Path.Combine(staging, "Setup.ps1");
            string package = Path.Combine(staging, Package);
            // All path values go through the process environment, outside PowerShell code.
            // The existing release engine verifies the portable package and every member.
            const string command = "$ErrorActionPreference='Stop'; try { . $env:LT_INSTALL_SCRIPT; " +
                "Install-Portable $env:LT_INSTALL_PACKAGE $env:LT_INSTALL_BASE $env:LT_INSTALL_MENU | Out-Null " +
                "} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }";
            var start = new ProcessStartInfo {
                FileName = Path.Combine(Environment.SystemDirectory, @"WindowsPowerShell\v1.0\powershell.exe"),
                Arguments = "-NoLogo -NoProfile -NonInteractive -STA -ExecutionPolicy RemoteSigned -Command \"" + command + "\"",
                WorkingDirectory = staging,
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true
            };
            start.EnvironmentVariables["LT_INSTALL_SCRIPT"] = script;
            start.EnvironmentVariables["LT_INSTALL_PACKAGE"] = package;
            start.EnvironmentVariables["LT_INSTALL_BASE"] = installBase ?? defaultBase;
            start.EnvironmentVariables["LT_INSTALL_MENU"] = startMenu ?? defaultMenu;
            start.EnvironmentVariables.Remove("PSModulePath");
            using (var setupLock = File.Open(script, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var manifestLock = File.Open(Path.Combine(staging, "files.json"), FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var launcherLock = File.Open(Path.Combine(staging, "LiveTranslate.Launcher.exe"), FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                CheckHash(setupLock, GeneratedPins.ScriptHash);
                CheckHash(launcherLock, GeneratedPins.LauncherHash);
                CheckHash(manifestLock, GeneratedPins.ManifestHash);
                using (var engine = Process.Start(start))
                {
                    string error = engine.StandardError.ReadToEnd().Trim();
                    engine.WaitForExit();
                    if (engine.ExitCode != 0)
                        throw new IOException(error.Length > 0 ? error : "Windows setup stopped before it finished.");
                }
            }
        }

        internal static void Install(Action<string> report)
        {
            string staging = Path.Combine(Path.GetTempPath(), "LiveTranslate-setup-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(staging);
            try
            {
                report("Checking and unpacking the offline installer...");
                Extract(staging);
                report("Installing LiveTranslate and creating your Start menu shortcut...");
                InstallFrom(staging, null, null);
            }
            finally
            {
                // Delete only the known embedded files from this per-run staging folder.
                try
                {
                    foreach (string name in PayloadFiles) File.Delete(Path.Combine(staging, name));
                    Directory.Delete(staging, false);
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
    }
}
