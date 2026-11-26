using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;
using LiveTranslate;

// Build with ReleaseHistory.cs, WindowTheme.cs, ModernControls.cs and
// WorkspaceGlyphs.cs to run the offline dialog on its own.
internal static class CheckReleaseHistory
{
    private static void Require(bool passed, string message)
    {
        if (!passed) throw new InvalidOperationException(message);
    }

    [STAThread]
    private static void Main()
    {
        Application.EnableVisualStyles();
        using (var window = new ReleaseHistoryWindow(SystemFonts.MessageBoxFont))
        {
            window.ShowInTaskbar = false;
            window.StartPosition = FormStartPosition.Manual;
            window.Location = new Point(-20000, -20000);
            window.Show();
            Application.DoEvents();
            var versions = (ComboBox)window.Controls.Find("ReleaseVersion", true)[0];
            var notes = (TextBox)window.Controls.Find("ReleaseNotes", true)[0];
            var unique = new HashSet<string>();
            var previous = new Version(Int32.MaxValue, 0);
            Require(versions.SelectedIndex == 0 && versions.Text == "0.8.0", "Expected current release selected");
            Require(versions.TabStop && notes.TabStop && !String.IsNullOrWhiteSpace(versions.AccessibleName) &&
                    !String.IsNullOrWhiteSpace(notes.AccessibleName), "Missing keyboard or accessibility support");
            for (int i = 0; i < versions.Items.Count; i++)
            {
                versions.SelectedIndex = i;
                var item = (ReleaseNote)versions.SelectedItem;
                var version = new Version(item.Version);
                Require(version < previous && unique.Add(item.Version), "Versions must be unique and newest first");
                Require(!String.IsNullOrWhiteSpace(item.Title) && item.Changes.Length > 0, "Release missing notes");
                foreach (string change in item.Changes)
                    Require(notes.Text.Contains(change), "Release notes did not refresh for " + item.Version);
                previous = version;
            }
            Require(unique.Count == 21 && versions.Text == "0.1", "Incomplete archived release history");
            Require(SystemInformation.HighContrast || (window.BackColor.GetBrightness() < .2F && notes.BackColor.GetBrightness() < .2F),
                "Changelog and read-only notes must use the dark application theme");
            window.ClientSize = new Size(355, 290);
            window.PerformLayout();
            Require(notes.Visible && notes.ClientSize.Height > 40 && notes.ScrollBars == ScrollBars.Vertical,
                "Release notes must remain readable in a small window");
            Require(window.CancelButton != null, "Escape must dismiss changelog");
            Console.WriteLine("PASS: All 21 release notes from 0.8.0 to 0.1 open offline; ordering, keyboard access, text selection, dark theme and compact layout passed.");
        }
    }
}
