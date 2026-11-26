# LiveTranslate 0.8.1 for Windows 11 x64

The 0.8.1 patch fixes a reproduced covered-area capture failure and a selected-language recognition safeguard bypass. **Read once** and **Preview** briefly clear overlapping LiveTranslate windows so the text behind them can be sampled, then restore their appearance and focus. Continuous watching reports an obstructed target instead of silently scanning a blanked area; minimize the dashboard or choose an application target. Put test text in the browser or target application, rather than LiveTranslate's own input field, which is excluded to prevent feedback.

**Preview** is now beside Capture area. The separate **Recognition details** tab shows what OCR claimed and what the source filter accepted, clearly marked as diagnostic. Those readings can be incorrect and are not themselves captions. Preview is one frame; close and reopen it to refresh. No screenshots or audio recordings are saved automatically.

Whole-scene icon and fragment checks now apply when Chinese, Korean or Japanese is selected explicitly, as well as under Auto. Repeated identical source/translation flaps within a short interval no longer flood the transcript, while genuine A → B → A content changes remain visible. For an intentionally ambiguous one-character sign, choose its language and draw a tight area; whole-scene reading remains conservative.

**Audio setup** shows measured input, silence or missing packets, detected language/confidence and recognition decisions. The diagnostic source box can show unconfirmed words without putting them into captions. A level meter confirms signal reception, not translation accuracy. Base remains the default recognizer. **Install Small (~464 MiB)** downloads only the existing checked speech model; once ready, **Use Small model** selects it explicitly. A selected model is remembered. Small was slower and was not consistently better in local comparisons; natural accents and Auto recognition in the reported setup still need retesting.

**Settings → VR captions** now has a **Background opacity** slider from transparent to opaque, with text kept opaque. Select the connection profile to retain different width, distance, height and opacity for SteamVR, Virtual Desktop + SteamVR, Steam Link + SteamVR or Quest Link + SteamVR. This selector restores app layouts; it does not switch the system runtime. OpenXR/VDXR is clearly unavailable and cannot start the SteamVR backend. Native captions also show the source label so SCREEN and AUDIO results can be distinguished.

The 0.8.0 feature update adds native SteamVR captions, application-window capture and a capture preview. Screen-reading status explains whether an image is unavailable, no supported text is confirmed, or translation succeeded. Speech recording retains longer pauses between words and prefers a quiet boundary when a phrase reaches its time limit.

For Quest 3S with Virtual Desktop, run VRChat through **SteamVR**. Choose **Open captions → Native VR captions (SteamVR)** or **Settings → VR captions → Start VR captions**. Captions follow your view below centre and continue while the dashboard is minimized. Adjust width, distance and vertical offset in VR caption settings. This output uses SteamVR directly and does not need a wrist-attached desktop window or a second monitor. VDXR/OpenXR sessions and standalone VRChat do not have an overlay backend yet. Physical headset readability and reconnect behavior still need field verification.

For text in VRChat, choose its application under **Capture area**, then use **Preview captured view** to confirm the image. Keep VRChat restored and rendering. Some GPU-rendered windows do not supply a background image; a failed preview reports this instead of substituting the desktop. Application capture reads the PC application's view, not a direct headset framebuffer. A native output overlay and a usable OCR input are separate requirements.

Automatic screen reading covers Chinese, Korean and Japanese. Choose **German**, **Italian** or **Spanish** explicitly for those scripts. Under **Settings → Language files → Get more text languages**, the existing multilingual text model and matching German, Italian and Spanish OCR files can be prepared in the app's own data folder. They add about 607 MiB. This optional text model is for personal, noncommercial use. Prepare the files on each PC; a code update preserves models but does not bundle these downloads. Actual accents, arbitrary wording, small game fonts and busy backgrounds still require testing.

The 0.7.1 patch gives selectors, settings tabs, input borders, numeric buttons and scrollbars a consistent dark surface. Focus remains visible, and the styling applies within LiveTranslate. Windows theme preferences are unchanged.

## The new workspace

Use the sidebar to move between **Live session**, **Session history**, **Audio setup**, and **Settings**. Navigation keeps your current capture session and the same transcript. The dark interface uses mint controls and purple source text.

**Audio setup** selects the actual Windows input and source language; translations currently target English. **Live session** also keeps screen watching, capture area, one-shot reading, pasted text, and reply practice available. **Pause translation** remembers the active inputs so they can resume; **End session** stops capture while keeping the transcript. **Save transcript** exports only when you choose a file. History is the current app session's newest 180 captions, not an automatic recording archive.

**Open captions** offers either desktop captions or native SteamVR captions. The desktop window keeps original text, translation, pinning, pause, and dashboard controls. Native VR captions display the real incoming caption state independently of that window.

Open **Settings → Updates** for public GitHub updates. Major interface or feature releases start at 0.x.0; fixes for 0.8 use 0.8.1, 0.8.2, and so on.

Open **LiveTranslate** from the Windows Start menu or double-click **LiveTranslate.exe** in the application folder. The installed folder groups maintenance commands in **scripts**, model and dependency configuration in **config**, and guides and notices in **docs**. Models, runtime files and language packs continue to use their own folders.

## Practice a reply

On the dashboard, open **Practice a reply** under **Translate text**. Choose a **Reply language** and a **Starter phrase**, then select **Translate reply**. **Translated reply** and **Phonetic spelling** appear separately. You decide when to say or copy the reply.

The four starter targets are Japanese, Korean, Simplified Chinese and Traditional Chinese. Practice the built-in examples while offline. For custom replies, prepare the optional written-language model in **Settings → Language files → Get more text languages**, then reopen the app. The model adds about 601 MiB and is licensed for noncommercial use.

Each of the 20 starter choices has a romanized reading and an approximate English sound cue. Chinese uses pinyin with tone marks, Japanese uses romaji and Korean uses a Latin-alphabet reading. Use the sound cue as a starting point, especially with Mandarin tones.

For custom replies, pronunciation support depends on the target and wording. If the app cannot supply a reading, you can still read and copy the translation. Custom translations use a model with 201 target language and script entries. Six targets have been exercised with that model in this release.

## Field testing

Start desktop testing on a cropped, mixed-language panel. Leave a foreign line beside an English line, change the foreign wording, then remove it. Check placement, stable wording, response time, clearing, and whether the English line stays visible. Use a moving subtitle and your usual monitor scaling on a second pass.

For a headset test, use PC VRChat through SteamVR. Select the Windows playback device carrying the game, enable **Auto listen**, then start **Native VR captions (SteamVR)**. Minimize the dashboard and return to VRChat on the same monitor. Verify readable placement, expiry and reconnect behavior. For OCR, select the VRChat application and check its preview first. Screen capture and game audio are independent, so turn Watch screen off during a voice-only trial.

## Reading live captions

Choose the source language and turn on the inputs you want. **Watch screen** places English over detected text. **Auto listen** translates your microphone, computer audio, or both, depending on the selected audio source. The language picker shows which inputs have their files ready.

The **Live captions** transcript follows new translations until you scroll up or select text to copy. Scroll back to the bottom to follow the conversation again. The dashboard retains the newest 180 entries. Use **Source text** to check a translation against the original.

Use **Open captions** to choose the caption display. Long captions page through their text automatically. The desktop caption window also supports manual reading controls. If a selected monitor disappears, screen capture waits for that display; an unavailable application reports that source instead of switching to another window. Choose a different capture target to switch.

## Spoken English and updates

Open **Settings → Spoken English** to hear accepted voice translations through a locally installed English voice. Spoken output starts off. Choose your headset or Windows output there and keep **Auto listen** enabled for the input you want translated. Rate and volume affect the generated voice. English-only input stays filtered. Background dialogue, music, and microphone pickup of speaker playback can reduce recognition accuracy.

Open **Settings → Updates** and choose **Check for updates**. The app checks the public [LiveTranslate GitHub Releases channel](https://github.com/tokinmew/LiveTranslate/releases/latest). No GitHub account or sign-in is needed. Update files stored on your PC and previously selected sources are ignored. If GitHub cannot be reached, the app reports the failure instead of reporting that an older local release is current.

The official GitHub stable feed is pinned to this project's RSA-3072 public key. The client verifies the publisher signature and downloaded source hashes before compiling, scanning and installing a newer version. Only published stable releases from the official public repository are accepted.

Translate your screen, pasted text, microphone or computer audio into English. Recognition and translation run on your PC. The searchable language picker puts Asian languages first, with Traditional Chinese, Simplified Chinese, Japanese and Korean at the top. Each language shows availability separately for speech, text and screen.

## First launch

Open the Windows setup application and select **Install**. Open **LiveTranslate** when setup finishes. If you are using the portable ZIP, extract the complete folder to a writable location and open **LiveTranslate.exe**. Allow about 3 GB of free space. First launch prepares and checks the runtime, four starter text packs, five OCR packs and multilingual Whisper Base. Later launches reuse these files.

| Input | Using it |
| --- | --- |
| Screen | **Watch screen** starts on the primary display. Use **Capture area** for another display, a subtitle region or a vertical Japanese column. Select a specific source language for expanded screen languages. Whole-scene reading rejects ambiguous isolated symbols; choose the matching language and a tight drawn area for an intentional one-character sign. Text over clothing or other patterns can still be missed or misread. |
| Written text | Choose the source language and paste a passage. English-only lines are filtered. Short words shared with English can be skipped. |
| Games, videos and calls | Choose **Computer audio**, then turn on **Auto listen**. If speech is not received, choose the output actually used by the game or chat app. |
| Voices in the room | Choose your microphone or **Computer + microphone**. Turn **Auto listen** off to release the inputs. |
| PC VR | Run VRChat through SteamVR, then **Open captions → Native VR captions (SteamVR)**. Minimize the dashboard and keep VRChat rendering. Choose its application and preview it for OCR; choose the playback device carrying the game for audio. |

The desktop overlay draws English inside the detected words' coordinates and samples the background around the original lettering. Long translations, animation and imprecise text boxes can affect its appearance. Speech appears separately. The transcript keeps the full text. Native SteamVR captions use the placement set in VR caption settings. Headset-only pixels and standalone Quest apps require a different capture path.

## Expand your languages

The four starter profiles include written translation and OCR. Whisper Base has 98 non-English source-language tokens for speech. Accuracy varies with language, noise and duration. During a listening session, a repeated recognized phrase reuses its first accepted wording.

Open **Settings**, go to the language files and choose **Get more text languages**. The optional **601 MiB** NLLB pack provides **201 non-English written language and script entries** in total, including the starter languages. It is licensed for noncommercial use. The installer verifies four files by byte count and SHA-256, scans them with Microsoft Defender and can resume an interrupted download. Restart the dashboard when setup finishes.

For additional speech models, **scripts/Install quality models.cmd** includes a larger Whisper model, SenseVoice and the same NLLB text pack. If you already installed the quality models, the dashboard can use the existing NLLB files. See **QUALITY-SETUP.txt** and, for the optional Korean GPU setup, **KOREAN-DIALOGUE.txt**.

Screen reading needs both a text translation model and a compatible OCR reader. The picker reflects local availability. An English Windows reader can handle certain adequately identified Latin-script lines with lower accent accuracy. Native-language OCR improves recognition. A tight capture area helps with columns and dense subtitles.

## Updates

In a prepared copy with the updater, open **Settings**, **Updates**, then **Check for updates**. Choose **Download and restart** to install. The updater verifies the release hashes, compiles the dashboard and checks the staged update with Microsoft Defender. It preserves existing models, runtime and settings.

Updates must first be signed and published to the official public GitHub repository. The app offers no local-manifest or custom-server option. Older versions retain their original update controls until upgraded to this version.

The transcript can show the original words alongside the translation. **VALIDATION.md** contains release test results and limitations. **SOURCE-CHECKS.md**, **THIRD_PARTY.md** and **quality/MODEL-NOTICES.txt** document the supporting files. **scripts/Build.cmd** rebuilds the Windows dashboard and OCR helper from source.
