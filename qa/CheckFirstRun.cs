using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using LiveTranslate;

internal class CheckFirstRun
{
    internal static int Main(string[] args)
    {
        string root = Path.GetFullPath(args[0]);
        Directory.CreateDirectory(root);
        if (!FirstRun.EnsureReady(root)) throw new Exception("Source-only edition cannot open its dashboard.");

        string[] files = {
            "LiveTranslate.exe", "runtime/python.exe", "runtime/ready.txt", "model-test-results/offline-43c2c21bc9c17193.ok",
            "data/text-packs/zh_en/model/model.bin", "data/text-packs/zt_en/model/model.bin",
            "data/text-packs/ja_en/model/model.bin", "data/text-packs/ko_en/model/model.bin",
            "data/speech/base/model.bin", "data/speech/base/config.json", "data/speech/base/tokenizer.json", "data/speech/base/vocabulary.txt",
            "data/tessdata/chi_sim.traineddata", "data/tessdata/chi_tra.traineddata", "data/tessdata/jpn.traineddata",
            "data/tessdata/jpn_vert.traineddata", "data/tessdata/kor.traineddata"
        };
        foreach (string file in files)
        {
            string path = Path.Combine(root,file);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, "fixture");
        }
        Directory.CreateDirectory(Path.Combine(root, "payload"));
        if (!FirstRun.IsReady(root) || !FirstRun.EnsureReady(root)) throw new Exception("Prepared edition should open directly.");
        foreach (string file in files)
        {
            string path = Path.Combine(root, file);
            File.Delete(path);
            if (FirstRun.IsReady(root)) throw new Exception("Missing " + file + " was accepted.");
            File.WriteAllText(path, "fixture");
        }

        string scripts = Path.Combine(root, "scripts");
        Directory.CreateDirectory(scripts);
        string script = Path.Combine(scripts, "Prepare-Offline.ps1");
        File.WriteAllText(Path.Combine(root, "Prepare-Offline.ps1"), "throw 'Used wrong root-level script'");
        File.WriteAllText(script, "Write-Output 'Unpacking the Windows runtime'\r\nWrite-Output 'Preparing the 13 original language files'\r\n", Encoding.ASCII);
        List<string> progress = new List<string>();
        FirstRun.Prepare(root, progress.Add);
        if (progress.Count != 2) throw new Exception("Missing preparation progress.");
        File.WriteAllText(script, "[Console]::Error.WriteLine('Synthetic failure'); exit 9", Encoding.ASCII);
        try { FirstRun.Prepare(root, progress.Add); throw new Exception("Preparation failure suppressed."); }
        catch (IOException ex) { if (ex.Message != "Synthetic failure") throw; }
        Console.WriteLine("PASS: prepared entry point, source-only edition, 17 readiness checks, fixed script inside scripts/, progress and preparation failure");
        return 0;
    }
}
