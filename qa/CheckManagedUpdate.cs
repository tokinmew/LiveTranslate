using System;
using System.IO;

// Use a disposable directory, without registering the probe in Installed Apps.
internal static class CheckManagedUpdate
{
    private static void Require(bool truth) { if (!truth) throw new InvalidOperationException("Managed update regression"); }

    private static void Main(string[] args)
    {
        string root = Path.GetFullPath(args[0]);
        string owner = "LiveTranslate per-user desktop setup|" + root;
        Require(ManagedLayout.NeedsVersionRefresh(root, owner, "0.6.8", "0.6.9"));
        Require(!ManagedLayout.NeedsVersionRefresh(root, owner, "0.6.9", "0.6.9"));
        Require(!ManagedLayout.NeedsVersionRefresh(root, owner, "0.7.0", "0.6.9"));
        Require(!ManagedLayout.NeedsVersionRefresh(root, "Custom installer", "0.6.8", "0.6.9"));
        Require(!ManagedLayout.NeedsVersionRefresh(root, owner + "-different", "0.6.8", "0.6.9"));
        LayoutMigration.Organize(root);
        LayoutMigration.Organize(root);
        Console.WriteLine("PASS managed update registration and retry");
    }
}
