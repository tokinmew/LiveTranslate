using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32;

internal static class ManagedLayout
{
    private const string Adapter = "# LiveTranslate 0.6.8 organized-install compatibility";
    private static readonly HashSet<string> InstalledEngines = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
        "281cddb74c1d028b80e5accb5f2e58dc579875492a758e120bb7bbc70d619292",
        "02bd2bec07f20153a7a1db8acb9343be73a880567e96a0a330a2e6e0076a3938",
        "7eb39096cb5cb5e90adb2c1dca590a74be74b676e361f3acc1a096719afc68fe",
        "748e00702e64c07d7f47b22dd5d70ebdcaf3f0682d7929b29ff14c74543cad04"
    };

    internal static void Update(string root)
    {
        string parent = Path.GetDirectoryName(root);
        if (parent == null || !String.Equals(Path.GetFileName(root), "app", StringComparison.OrdinalIgnoreCase)) return;
        string marker = Path.Combine(parent, ".managed");
        LayoutMigration.Plain(marker);
        if (!File.Exists(marker) || File.ReadAllText(marker) != "LiveTranslate Windows per-user install v1") return;
        string support = Path.Combine(root, ".lt-setup");
        string script = Path.Combine(support, "Setup.ps1");
        LayoutMigration.Plain(support);
        LayoutMigration.Plain(script);
        if (!File.Exists(script)) throw new IOException("Repair the previous managed installation before upgrading it.");
        byte[] bytes = File.ReadAllBytes(script);
        string source = Encoding.UTF8.GetString(bytes).TrimStart('\ufeff');
        if (!source.StartsWith(Adapter + "\r\n", StringComparison.Ordinal))
        {
            // A newer graphical installer can preserve preexisting loose user files.
            // Its own manifest already describes organized paths and shortcut targets.
            if (source.Contains("$releaseVersion = [version]'0.6.8'")) return;
            if (!InstalledEngines.Contains(LayoutMigration.Hash(bytes)))
                throw new IOException("This installation has a custom or unknown uninstaller. Use the full LiveTranslate 0.6.8 installer to upgrade it.");
            string revised = Adapt(source);
            byte[] body = Encoding.UTF8.GetBytes("\ufeff" + revised);
            LayoutMigration.Write(script, body, LayoutMigration.Archive(root, "managed", "Setup.ps1"));
        }

        string defaultRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "LiveTranslate", "app");
        if (!String.Equals(root, defaultRoot, StringComparison.OrdinalIgnoreCase)) return;
        string menu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "LiveTranslate");
        Retarget(root, menu);
        using (var record = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\LiveTranslate", true))
        {
            if (record != null && String.Equals(record.GetValue("LiveTranslateSetupOwner") as string,
                    "LiveTranslate per-user desktop setup|" + root, StringComparison.OrdinalIgnoreCase))
                record.SetValue("DisplayVersion", "0.6.8");
        }
    }

    private static string Adapt(string original)
    {
        const string record = "$file = Under $appDir $record[0]";
        const string removal = "        Setup-Links $menu $appDir $true";
        if (original.IndexOf(record, StringComparison.Ordinal) < 0 || original.IndexOf(removal, StringComparison.Ordinal) < 0)
            throw new InvalidDataException("The previous uninstaller format is unsupported.");
        var legacy = new StringBuilder("$organized = @{\r\n");
        foreach (string[] item in LayoutFiles.Entries)
        {
            if (!item[0].StartsWith("quality/", StringComparison.Ordinal))
                legacy.Append("  '").Append(Path.GetFileName(item[0])).Append("' = '").Append(item[0]).Append("'\r\n");
        }
        legacy.Append("}\r\n");
        const string newPath = "$relative = [string]$record[0]; if ($organized.ContainsKey($relative)) { $relative = $organized[$relative] }; $file = Under $appDir $relative";
        var extra = new StringBuilder("        if (!$erase) { foreach ($owned in @(\r\n");
        foreach (string name in LayoutFiles.SourcePaths)
            extra.Append("            '").Append(name).Append("'\r\n");
        extra.Append("        )) { $p = Under $appDir $owned; Plain-Path $p; if ([IO.File]::Exists($p)) { [IO.File]::Delete($p) } } }\r\n");
        // Older engines only recognize their former Start.cmd or graphical helper
        // link on uninstall. Remove the retargeted link only if it is still ours.
        extra.Append("        $linkFile = Under $menu 'LiveTranslate.lnk'; Plain-Path $menu; Plain-Path $linkFile\r\n" +
            "        if ([IO.File]::Exists($linkFile)) {\r\n" +
            "            $s = New-Object -ComObject WScript.Shell; try { $l = $s.CreateShortcut($linkFile); try {\r\n" +
            "                if ($l.TargetPath -ieq (Under $appDir 'LiveTranslate.exe') -and !$l.Arguments) { [IO.File]::Delete($linkFile) }\r\n" +
            "            } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($l) } } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($s) }\r\n" +
            "        }\r\n");
        // PowerShell's param() must stay the first non-comment statement.
        return Adapter + "\r\n" + original.Replace("function Uninstall-Portable", legacy + "\r\nfunction Uninstall-Portable")
            .Replace(record, newPath).Replace(removal, extra.ToString() + removal);
    }

    internal static void Retarget(string root, string menu)
    {
        string file = Path.Combine(menu, "LiveTranslate.lnk");
        LayoutMigration.Plain(menu);
        LayoutMigration.Plain(file);
        if (!File.Exists(file)) return;
        object shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell", true));
        object link = null;
        try
        {
            link = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { file });
            Type type = link.GetType();
            string target = (string)type.InvokeMember("TargetPath", BindingFlags.GetProperty, null, link, null);
            string args = (string)type.InvokeMember("Arguments", BindingFlags.GetProperty, null, link, null);
            if (!String.IsNullOrEmpty(args) || (!String.Equals(target, Path.Combine(root, "Start.cmd"), StringComparison.OrdinalIgnoreCase) &&
                !String.Equals(target, Path.Combine(root, ".lt-setup", "LiveTranslate.Launcher.exe"), StringComparison.OrdinalIgnoreCase))) return;
            type.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { Path.Combine(root, "LiveTranslate.exe") });
            type.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { root });
            type.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
        }
        finally
        {
            if (link != null) Marshal.FinalReleaseComObject(link);
            Marshal.FinalReleaseComObject(shell);
        }
    }
}
