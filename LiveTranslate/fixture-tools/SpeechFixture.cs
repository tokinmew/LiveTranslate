using System;
using System.Collections.Generic;
using System.IO;
using System.Speech.AudioFormat;
using System.Speech.Synthesis;
using System.Text;
using System.Web.Script.Serialization;

[assembly: System.Reflection.AssemblyTitle("Live Translate Speech Fixture")]
[assembly: System.Reflection.AssemblyProduct("Live Translate")]
[assembly: System.Reflection.AssemblyDescription("Creates fixed local speech samples with installed Windows voices")]
[assembly: System.Reflection.AssemblyVersion("0.3.1.0")]
[assembly: System.Reflection.AssemblyFileVersion("0.3.1.0")]

namespace LiveTranslate.FixtureTools
{
    /// <summary>
    /// A local fixture generator, not a recognizer or recorder. It reads installed
    /// Windows voices and synthesizes one of four fixed test sentences. It does
    /// not launch another process, change settings, or access the network.
    /// </summary>
    internal static class SpeechFixture
    {
        private const int SampleRate = 16000;
        private const short Channels = 1;
        private const short BitsPerSample = 16;

        [STAThread]
        private static int Main(string[] args)
        {
            Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
            Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush = true });

            try
            {
                if (args.Length == 1 && args[0] == "--list")
                {
                    WriteJson(ListVoices());
                    return 0;
                }

                if (args.Length == 4 && args[0] == "--speak")
                {
                    WriteJson(CreateFixture(args[1], args[2], args[3]));
                    return 0;
                }

                Console.Error.WriteLine("Usage: SpeechFixture.exe --list");
                Console.Error.WriteLine("   or: SpeechFixture.exe --speak <voice-name> <zh|ja|ko|en> <new-wav-path>");
                return 2;
            }
            catch (Exception error)
            {
                // Some Windows sessions (including restricted/headless ones)
                // cannot initialize System.Speech's default SAPI output token.
                // Report that limitation without changing any Windows setting.
                string code = error.GetType().Name;
                string message = error.Message;
                if (error is NullReferenceException)
                {
                    code = "windows_speech_unavailable";
                    message = "Windows speech synthesis could not initialize its default audio/voice service. Use a Windows desktop session with an available default audio output and an installed text-to-speech voice. No settings were changed.";
                }
                Console.Error.WriteLine(new JavaScriptSerializer().Serialize(new Dictionary<string, object>
                {
                    { "error", code },
                    { "message", message }
                }));
                return 1;
            }
        }

        private static void WriteJson(object value)
        {
            Console.Out.WriteLine(new JavaScriptSerializer().Serialize(value));
        }

        private static List<Dictionary<string, string>> ListVoices()
        {
            List<Dictionary<string, string>> result = new List<Dictionary<string, string>>();
            using (SpeechSynthesizer synthesizer = new SpeechSynthesizer())
            {
                foreach (InstalledVoice voice in synthesizer.GetInstalledVoices())
                {
                    if (!voice.Enabled || voice.VoiceInfo == null || voice.VoiceInfo.Culture == null)
                        continue;

                    result.Add(new Dictionary<string, string>
                    {
                        { "name", voice.VoiceInfo.Name },
                        { "culture", voice.VoiceInfo.Culture.Name }
                    });
                }
            }

            result.Sort(delegate(Dictionary<string, string> left, Dictionary<string, string> right)
            {
                int culture = StringComparer.OrdinalIgnoreCase.Compare(left["culture"], right["culture"]);
                return culture != 0 ? culture : StringComparer.OrdinalIgnoreCase.Compare(left["name"], right["name"]);
            });
            return result;
        }

        private static Dictionary<string, object> CreateFixture(string requestedVoice, string language, string path)
        {
            language = language.Trim().ToLowerInvariant();
            string phrase = Phrase(language);
            if (String.IsNullOrWhiteSpace(requestedVoice))
                throw new ArgumentException("Choose an enabled voice returned by --list.");
            if (String.IsNullOrWhiteSpace(path))
                throw new ArgumentException("An output WAV path is required.");

            string outputPath = Path.GetFullPath(path);
            if (!String.Equals(Path.GetExtension(outputPath), ".wav", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("The output filename must end in .wav.");
            string directory = Path.GetDirectoryName(outputPath);
            if (!Directory.Exists(directory))
                throw new DirectoryNotFoundException("The output directory does not exist: " + directory);
            if (File.Exists(outputPath))
                throw new IOException("The output file already exists. Choose a new WAV path.");

            string voiceName;
            string culture;
            string temporaryPath = null;
            try
            {
                using (SpeechSynthesizer synthesizer = new SpeechSynthesizer())
                {
                    InstalledVoice selected = null;
                    foreach (InstalledVoice voice in synthesizer.GetInstalledVoices())
                    {
                        if (voice.Enabled && voice.VoiceInfo != null && voice.VoiceInfo.Culture != null && String.Equals(voice.VoiceInfo.Name, requestedVoice, StringComparison.OrdinalIgnoreCase))
                        {
                            selected = voice;
                            break;
                        }
                    }

                    if (selected == null)
                        throw new ArgumentException("That enabled Windows voice was not found. Run --list to see available voices.");
                    if (!String.Equals(selected.VoiceInfo.Culture.TwoLetterISOLanguageName, language, StringComparison.OrdinalIgnoreCase))
                        throw new ArgumentException("The selected voice does not match " + language + ". Choose a matching voice from --list.");

                    voiceName = selected.VoiceInfo.Name;
                    culture = selected.VoiceInfo.Culture.Name;
                    synthesizer.SelectVoice(voiceName);
                    synthesizer.Rate = 0;
                    synthesizer.Volume = 100;

                    // Reserve our own temporary filename. SetOutputToWaveFile
                    // overwrites this reservation, never a user's existing WAV.
                    temporaryPath = outputPath + "." + Guid.NewGuid().ToString("N") + ".tmp.wav";
                    using (FileStream reservation = new FileStream(temporaryPath, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { }
                    SpeechAudioFormatInfo format = new SpeechAudioFormatInfo(
                        SampleRate, AudioBitsPerSample.Sixteen, AudioChannel.Mono);
                    synthesizer.SetOutputToWaveFile(temporaryPath, format);
                    synthesizer.Speak(phrase);
                    synthesizer.SetOutputToNull();
                }

                long frames = VerifyWave(temporaryPath);
                // File.Move fails if the destination appeared while synthesis
                // was running, preserving that existing file too.
                File.Move(temporaryPath, outputPath);
                temporaryPath = null;
                return new Dictionary<string, object>
                {
                    { "ok", true },
                    { "voice", voiceName },
                    { "culture", culture },
                    { "language", language },
                    { "phrase", phrase },
                    { "path", outputPath },
                    { "sample_rate", SampleRate },
                    { "channels", Channels },
                    { "bits_per_sample", BitsPerSample },
                    { "frames", frames }
                };
            }
            catch
            {
                // Only our temporary file is removed on failure.
                if (temporaryPath != null)
                {
                    try { File.Delete(temporaryPath); }
                    catch { }
                }
                throw;
            }
        }

        private static string Phrase(string language)
        {
            switch (language)
            {
                case "zh":
                    return "\u706b\u8eca\u4e94\u9ede\u51fa\u767c\u3002"; // The train leaves at five.
                case "ja":
                    return "\u96fb\u8eca\u306f\u4e94\u6642\u306b\u51fa\u767a\u3057\u307e\u3059\u3002";
                case "ko":
                    return "\uae30\ucc28\ub294 \ub2e4\uc12f \uc2dc\uc5d0 \ucd9c\ubc1c\ud569\ub2c8\ub2e4.";
                case "en":
                    return "The train leaves at five.";
                default:
                    throw new ArgumentException("Supported fixture language codes: zh, ja, ko, en.");
            }
        }

        /// <summary>Checks the produced RIFF file instead of assuming that the requested format was honored.</summary>
        private static long VerifyWave(string path)
        {
            using (BinaryReader reader = new BinaryReader(File.OpenRead(path), Encoding.ASCII))
            {
                if (ReadFourCc(reader) != "RIFF")
                    throw new InvalidDataException("Speech synthesis did not produce a RIFF WAV file.");
                reader.ReadUInt32();
                if (ReadFourCc(reader) != "WAVE")
                    throw new InvalidDataException("Speech synthesis did not produce a WAVE file.");

                bool formatValid = false;
                long dataBytes = -1;
                while (reader.BaseStream.Position + 8 <= reader.BaseStream.Length)
                {
                    string chunk = ReadFourCc(reader);
                    uint length = reader.ReadUInt32();
                    long next = reader.BaseStream.Position + length + (length & 1);
                    if (next > reader.BaseStream.Length)
                        throw new InvalidDataException("The synthesized WAV file contains an incomplete chunk.");

                    if (chunk == "fmt ")
                    {
                        if (length < 16)
                            throw new InvalidDataException("The synthesized WAV file has an invalid format chunk.");
                        ushort encoding = reader.ReadUInt16();
                        ushort channels = reader.ReadUInt16();
                        uint sampleRate = reader.ReadUInt32();
                        reader.ReadUInt32();
                        ushort blockAlign = reader.ReadUInt16();
                        ushort bits = reader.ReadUInt16();
                        formatValid = encoding == 1 && channels == Channels && sampleRate == SampleRate && blockAlign == 2 && bits == BitsPerSample;
                    }
                    else if (chunk == "data")
                    {
                        dataBytes = length;
                    }

                    reader.BaseStream.Position = next;
                }

                if (!formatValid || dataBytes <= 0 || (dataBytes & 1) != 0)
                    throw new InvalidDataException("The synthesized WAV must contain nonempty 16 kHz mono 16-bit PCM audio.");
                return dataBytes / 2;
            }
        }

        private static string ReadFourCc(BinaryReader reader)
        {
            byte[] value = reader.ReadBytes(4);
            if (value.Length != 4)
                throw new EndOfStreamException("The synthesized WAV file ended unexpectedly.");
            return Encoding.ASCII.GetString(value);
        }
    }
}
