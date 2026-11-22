using System;
using System.Globalization;
using System.IO;
using System.Threading;
using Windows.Foundation;
using Windows.Globalization;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Storage.Streams;

// In-memory, single-frame English word detector. The caller controls the
// timeout and can terminate this process without interrupting the WinForms UI.
internal static class EnglishOcr
{
    private static int Main()
    {
        try
        {
            OcrEngine engine = null;
            foreach (Language language in OcrEngine.AvailableRecognizerLanguages)
            {
                if (language.LanguageTag.Equals("en", StringComparison.OrdinalIgnoreCase) ||
                    language.LanguageTag.StartsWith("en-", StringComparison.OrdinalIgnoreCase))
                {
                    engine = OcrEngine.TryCreateFromLanguage(language);
                    if (engine != null) break;
                }
            }
            if (engine == null) return 2;
            using (var input = new BinaryReader(Console.OpenStandardInput()))
            {
                int width = input.ReadInt32();
                int height = input.ReadInt32();
                if (width <= 0 || height <= 0 || width > OcrEngine.MaxImageDimension ||
                    height > OcrEngine.MaxImageDimension || (long)width * height > 16000000) return 4;
                byte[] bytes = input.ReadBytes(width * height);
                if (bytes.Length != width * height) return 4;
                using (var bitmap = new SoftwareBitmap(BitmapPixelFormat.Gray8, width, height, BitmapAlphaMode.Ignore))
                using (var writer = new DataWriter())
                {
                    writer.WriteBytes(bytes);
                    bitmap.CopyFromBuffer(writer.DetachBuffer());
                    var operation = engine.RecognizeAsync(bitmap);
                    var info = (IAsyncInfo)operation;
                    try
                    {
                        while (info.Status == AsyncStatus.Started) Thread.Sleep(8);
                        var result = operation.GetResults();
                        int lineNumber = 0;
                        int count = 0;
                        foreach (var line in result.Lines)
                        {
                            foreach (var word in line.Words)
                            {
                                if (++count > 10000) return 4;
                                // The output contains only a printable ASCII word and pixel bounds.
                                // Non-Latin text never qualifies as a positive English observation.
                                if (String.IsNullOrEmpty(word.Text) || word.Text.Length > 128) continue;
                                bool printable = true;
                                foreach (char c in word.Text)
                                    if (c < '!' || c > '~') { printable = false; break; }
                                if (!printable) continue;
                                var b = word.BoundingRect;
                                Console.WriteLine(String.Format(CultureInfo.InvariantCulture,
                                    "{0}\t{1}\t{2}\t{3}\t{4}\t{5}", lineNumber, (int)b.Left,
                                    (int)b.Top, (int)Math.Ceiling(b.Right), (int)Math.Ceiling(b.Bottom), word.Text));
                            }
                            lineNumber++;
                        }
                    }
                    finally { info.Close(); }
                }
            }
            return 0;
        }
        catch (Exception)
        {
            // Do not emit captured text to logs on a native OCR error.
            return 3;
        }
    }
}
