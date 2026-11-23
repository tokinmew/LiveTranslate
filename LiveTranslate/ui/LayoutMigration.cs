using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

// The legacy updater commits its journal before this runs. Its normal run gate
// is held by Program.Main, so repair/another update cannot replace the app mid-move.
internal static class LayoutMigration
{
    internal static bool EnsureOrganized(string root)
    {
        try { Organize(root); return true; }
        catch (Exception error)
        {
            MessageBox.Show("The application folders could not be prepared. Close other setup or model windows and open LiveTranslate again.\r\n\r\n" +
                error.Message, "LiveTranslate setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return false;
        }
    }

    internal static void Plain(string path)
    {
        try
        {
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("This installation contains a linked path: " + path);
        }
        catch (FileNotFoundException) { }
        catch (DirectoryNotFoundException) { }
    }

    internal static string DirectoryAt(string parent, string name)
    {
        string path = Path.Combine(parent, name);
        Plain(path);
        Directory.CreateDirectory(path);
        Plain(path);
        return path;
    }

    internal static string Hash(byte[] data)
    {
        using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
    }

    private static bool Matches(string file, string hash)
    {
        Plain(file);
        if (!File.Exists(file)) return false;
        using (var stream = File.OpenRead(file))
        using (var sha = SHA256.Create())
            return String.Equals(BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", ""), hash, StringComparison.OrdinalIgnoreCase);
    }

    internal static string Archive(string root, string category, string basename, string version = "0.6.8")
    {
        string backup = DirectoryAt(DirectoryAt(DirectoryAt(root, "migration-backup"), version), category);
        string path = Path.Combine(backup, basename);
        Plain(path);
        return File.Exists(path) || Directory.Exists(path) ?
            Path.Combine(backup, Guid.NewGuid().ToString("N") + "-" + basename) : path;
    }

    internal static void Write(string path, byte[] data, string backup)
    {
        Plain(path);
        string temporary = Path.Combine(Path.GetDirectoryName(path), ".lt-layout-" + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            using (var writer = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                writer.Write(data, 0, data.Length);
                writer.Flush(true);
            }
            if (File.Exists(path)) File.Replace(temporary, path, backup);
            else File.Move(temporary, path);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    private static byte[] Contents(string[] entry)
    {
        using (var packed = new MemoryStream(Convert.FromBase64String(entry[2])))
        using (var unzip = new GZipStream(packed, CompressionMode.Decompress))
        using (var output = new MemoryStream())
        {
            unzip.CopyTo(output);
            byte[] data = output.ToArray();
            if (Hash(data) != entry[1]) throw new InvalidDataException("The layout resource changed: " + entry[0]);
            return data;
        }
    }

    private static FileStream Gate(string state)
    {
        string path = Path.Combine(state, "layout.lock");
        Plain(path);
        var elapsed = Stopwatch.StartNew();
        while (true)
        {
            try { return new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
            catch (IOException error)
            {
                int code = error.HResult & 65535;
                if ((code != 32 && code != 33) || elapsed.Elapsed.TotalSeconds > 10) throw;
                Thread.Sleep(80);
            }
        }
    }

    internal static void Organize(string root)
    {
        root = Path.GetFullPath(root);
        string driveRoot = Path.GetPathRoot(root);
        if (root.Length > driveRoot.Length) root = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        Plain(root);
        OrganizeFiles(root);
        ManagedLayout.RefreshRegistration(root);
    }

    private static void OrganizeFiles(string root)
    {
        string state = Path.Combine(root, ".livetranslate-update");
        string marker = Path.Combine(state, "layout-0.6.8.txt");
        Plain(state);
        Plain(marker);
        if (File.Exists(marker) && File.ReadAllText(marker) == LayoutFiles.Fingerprint) return;

        FileStream gate;
        try { gate = Gate(DirectoryAt(root, ".livetranslate-update")); }
        catch (UnauthorizedAccessException)
        {
            // The dashboard supports a completed installation on read-only media.
            foreach (string[] entry in LayoutFiles.Entries)
                if (!Matches(Path.Combine(root, entry[0]), entry[1]) ||
                    File.Exists(Path.Combine(root, Path.GetFileName(entry[0])))) throw;
            return;
        }
        using (gate)
        {
            if (File.Exists(marker) && File.ReadAllText(marker) == LayoutFiles.Fingerprint) return;
            var loose = new List<string>();
            // Copy canonical support files before removing any legacy entry point.
            // A stopped run can repeat every step; changed originals are archived.
            foreach (string[] entry in LayoutFiles.Entries)
            {
                string parent = entry[0].Split('/')[0];
                string basename = Path.GetFileName(entry[0]);
                string destination = Path.Combine(DirectoryAt(root, parent), basename);
                if (!Matches(destination, entry[1]))
                    Write(destination, Contents(entry), File.Exists(destination) ? Archive(root, parent, basename) : null);
                if (parent != "quality")
                {
                    string source = Path.Combine(root, basename);
                    Plain(source);
                    if (File.Exists(source)) loose.Add(source);
                }
            }

            if (loose.Count != 0)
            {
                // Legacy online preparation left a zero-length lock at top level.
                string oldLock = Path.Combine(root, "setup.lock");
                Plain(oldLock);
                if (File.Exists(oldLock) && new FileInfo(oldLock).Length == 0) loose.Add(oldLock);
                ManagedLayout.Update(root);
                foreach (string source in loose)
                {
                    Plain(source);
                    if (File.Exists(source))
                        File.Move(source, Archive(root, "previous-root", Path.GetFileName(source)));
                }
            }
            ManagedLayout.UpgradeOrganizedUninstaller(root);
            Write(marker, Encoding.ASCII.GetBytes(LayoutFiles.Fingerprint), null);
        }
    }
}
