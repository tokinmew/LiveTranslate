using System;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
using LiveTranslate;

internal static class CheckUpdatesUI
{
    private const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    private static int count;
    private static void Check(bool passed, string name)
    {
        if (!passed) throw new Exception(name);
        Console.WriteLine("PASS " + name);
        count++;
    }
    private static T Field<T>(MainForm form, string name)
    {
        return (T)typeof(MainForm).GetField(name, Instance).GetValue(form);
    }
    private static string Normalize(string value)
    {
        return (string)typeof(MainForm).GetMethod("NormalizedFeed", BindingFlags.Static | BindingFlags.NonPublic)
            .Invoke(null, new object[]{value});
    }
    private static bool Rejects(string value)
    {
        try { Normalize(value); }
        catch (TargetInvocationException e) { return e.InnerException is InvalidDataException; }
        return false;
    }
    private static void Click(Button button)
    {
        typeof(Button).GetMethod("OnClick",Instance).Invoke(button,new object[]{EventArgs.Empty});
    }
    [STAThread]
    private static void Main()
    {
        const string repo = "https://github.com/tokinmew/LiveTranslate";
        using (var f = new MainForm())
        {
            TextBox source = Field<TextBox>(f,"updateSource");
            string local = Normalize("");
            Check(source.Text == local && Field<bool>(f,"managedReleaseSource"),"local feed remains initial default");
            Click(Field<Button>(f,"githubUpdate"));
            Check(source.Text == repo && !Field<bool>(f,"managedReleaseSource"),"opt-in project release source");
            Check(Field<Label>(f,"updateSourceLabel").Text.Contains("stable"),"stable GitHub channel identified");
            Check(Field<Label>(f,"updateSourceHint").Text.Contains("gh auth login"),"private access guidance");
            Check(!Field<Button>(f,"installUpdate").Enabled,"switching source requires fresh update offer");
            source.Text = "https://github.com/example/Another-Release/";
            Check(Normalize(source.Text) == "https://github.com/example/Another-Release","custom repository with trailing slash");
            Check(Rejects(repo + "/releases/latest"),"repository subpath rejected");
            Check(Rejects("https://token@github.com/org/project"),"embedded credentials rejected");
            Check(Rejects(repo + "?token=example"),"query data rejected");
            Check(Rejects("http://github.com/org/project"),"remote cleartext rejected");
            Check(Normalize("https://updates.example/latest.json") == "https://updates.example/latest.json","existing HTTPS manifest preserved");
            Click(Field<Button>(f,"defaultUpdate"));
            Check(source.Text == local && Field<bool>(f,"managedReleaseSource"),"restore managed local feed");
            Check(Field<System.Diagnostics.Process>(f,"worker")==null,"no real capture in hidden UI");
        }
        Console.WriteLine(count + " update UI checks passed.");
    }
}
