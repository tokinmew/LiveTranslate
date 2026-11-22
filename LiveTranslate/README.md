# LiveTranslate 0.6.6 for Windows 11 x64

## Reading live captions

Choose the source language and turn on the inputs you want. **Watch screen** places English over detected text. **Auto listen** translates your microphone, computer audio, or both, depending on the selected audio source. The language picker shows which inputs have their files ready.

The **Live captions** transcript follows new translations until you scroll up or select text to copy. Scroll back to the bottom to follow the conversation again. The dashboard retains the newest 180 entries. Use **Source text** to check a translation against the original.

Open **VR captions** to view translations in a separate window. Long captions advance through their lines automatically. Interacting with the text lets you read at your own pace. If a selected monitor disappears, screen capture waits for that display. Choose a different capture area to switch immediately.

## Spoken English and updates

Open **Settings → Spoken English** to hear accepted voice translations through a locally installed English voice. Spoken output starts off. Choose your headset or Windows output there and keep **Auto listen** enabled for the input you want translated. Rate and volume affect the generated voice. English-only input stays filtered. Background dialogue, music, and microphone pickup of speaker playback can reduce recognition accuracy.

Use **Settings → Updates** to keep following the current local feed or choose **GitHub Releases**. The official project address is https://github.com/tokinmew/LiveTranslate. Private releases become available after the owner creates the dedicated private repository and publishes the signed assets. Private downloads require the free GitHub CLI signed into an account with access. The local feed also supports offline updates. The app displays its installed version on the Updates page.

The official GitHub stable feed is pinned to this project's RSA-3072 public key. The client verifies the publisher signature and downloaded source hashes before compiling, scanning and installing a newer version. A custom local or HTTPS feed has its own trust requirements. Choose one only if you trust its publisher to supply application code.

Translate your screen, pasted text, microphone or computer audio into English. Recognition and translation run on your PC. The searchable language picker puts Asian languages first, with Traditional Chinese, Simplified Chinese, Japanese and Korean at the top. Each language shows availability separately for speech, text and screen.

## First launch

Extract the full ZIP into a writable folder with around 3 GB free. Inside **LiveTranslate**, open **Start.cmd**. Keep the first setup window open while it checks and prepares the portable runtime, four starter text packs, five OCR packs and multilingual Whisper Base. Later launches reuse these files.

| Input | Using it |
| --- | --- |
| Screen | **Watch screen** starts on the primary display. Use **Capture area** for another display, a subtitle region or a vertical Japanese column. Select a specific source language for expanded screen languages. |
| Written text | Choose the source language and paste a passage. English-only lines are filtered. Short words shared with English can be skipped. |
| Games, videos and calls | Choose **Computer audio**, then turn on **Auto listen**. If the meter stays quiet, choose the output actually used by the game or chat app. |
| Voices in the room | Choose your microphone or **Computer + microphone**. Turn **Auto listen** off to release the inputs. |
| PC VR | Open **VR captions**. Inside the headset's PC desktop or window view, select **LiveTranslate VR captions** and pin it if the runtime offers pinning. For screen translation select a desktop game mirror. For voice translation select the playback device carrying the VR game or chat. |

The desktop overlay draws English inside the detected words' coordinates and samples the background around the original lettering. Long translations, animation and imprecise text boxes can affect its appearance. Speech appears separately. The transcript keeps the full text. In VR the caption window uses the placement you choose in your PC dashboard. Headset-only pixels and standalone Quest apps require a different capture path.

## Expand your languages

The four starter profiles include written translation and OCR. Whisper Base has 98 non-English source-language tokens for speech. Accuracy varies with language, noise and duration. During a listening session, a repeated recognized phrase reuses its first accepted wording.

Open **Settings**, go to the language files and choose **Get more text languages**. The optional **601 MiB** NLLB pack provides **201 non-English written language and script entries** in total, including the starter languages. It is licensed for noncommercial use. The installer verifies four files by byte count and SHA-256, scans them with Microsoft Defender and can resume an interrupted download. Restart the dashboard when setup finishes.

For additional speech models, **Install quality models.cmd** includes a larger Whisper model, SenseVoice and the same NLLB text pack. If you already installed the quality models, the dashboard can use the existing NLLB files. See **QUALITY-SETUP.txt** and, for the optional Korean GPU setup, **KOREAN-DIALOGUE.txt**.

Screen reading needs both a text translation model and a compatible OCR reader. The picker reflects local availability. An English Windows reader can handle certain adequately identified Latin-script lines with lower accent accuracy. Native-language OCR improves recognition. A tight capture area helps with columns and dense subtitles.

## Updates

In a prepared copy with the updater, open **Settings**, **Updates**, then **Check for updates**. Choose **Download and restart** to install. The updater verifies the release hashes, compiles the dashboard and checks the staged update with Microsoft Defender. It preserves existing models, runtime and settings.

Use your private release feed on this PC or enter your own trusted HTTPS manifest URL. For an older copy without the Updates page, extract the small **Existing-Install-Update** ZIP and open **Enable updates.cmd**. Select the folder that contains your original **Start.cmd** and **LiveTranslate.exe**.

The transcript can show the original words alongside the translation. **VALIDATION.md** contains release test results and limitations. **SOURCE-CHECKS.md**, **THIRD_PARTY.md** and **quality/MODEL-NOTICES.txt** document the supporting files. **Build.cmd** rebuilds the Windows dashboard and OCR helper from source.
