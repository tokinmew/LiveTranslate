# LiveTranslate 0.8.1 release testing

## 0.8.1 reproduced fixes and remaining field failures

A native test reproduced the 0.8.0 white capture rectangle when LiveTranslate covered an authored external Japanese text window. The revised manual lease captured the underlying pixels, and native OCR returned the complete sentence. Opacity, window placement, visibility and focus were restored; capture exceptions and worker-exit timeout cleanup were exercised. Continuous watching reports obstruction without repeatedly hiding the dashboard. No personal desktop region was sampled by this fixture.

Nine authored English/icon scenes were checked under Auto and each of four explicit starter profiles. Before the patch, selected-language modes yielded false OCR on 25 of the 45 combinations; Auto's nine stayed clear. After applying the existing whole-scene proof to selected CJK profiles, all 45 negatives stayed clear. A permanent 49-case native runner passed with the English helper available and deliberately unavailable. Thirty-six real-text comparisons had unchanged output versus baseline: 23 exact results and 13 existing misses or fragmentation. These are bounded controls, not a claim of perfect screen recognition or reproduction of A51's exact Home scene.

Transcript-repeat tests cover A → blank → A within 30 seconds, geometry updates, different translations and genuine A → B → A changes. Overlay clearing/restoration remains independent from suppression of repeated transcript entries. No English Home word blocklist was introduced.

Audio adds measured per-endpoint signal and bounded in-memory recognition diagnostics. Silence, missing callbacks, clipping, selected-language mismatch and uncertain/English suppression are distinguishable. Old endpoint callbacks terminate after rerouting. A 32-case offline comparison used Base and Small, normal and deliberately paused recordings, and Auto/explicit selection. All 24 foreign cases produced captions; eight English cases stayed empty. Small was slower and lost a clause in one Korean result. The reported Auto/accent failures remain human retest items; no blanket detector-threshold change is claimed.

Opacity render tests check 0%, 50% and 100% backgrounds with opaque text, keyboard/accessibility controls, first-frame opacity and persisted connection layouts. Profile selection uses the existing SteamVR backend. OpenXR/VDXR selection disables native start; no system runtime is changed. Physical Quest 3S/Virtual Desktop placement, readability, opacity and reconnect behavior remain field tests. Detailed final fixture and signed-update results are in the release receipt.

## Current field report and validation scope

The 0.7.2 field report failed genuine-text capture on PC/VRChat, reported poor speech accuracy under Auto and explicit source selection, and identified the desktop caption arrangement as unsuitable for a one-monitor VR session. The reported headset is Quest 3S through Virtual Desktop. Languages include the four Asian starter choices and German; Italian and Spanish are next. These human failures remain open until retested. A subjective "50/50" description is not a measured accuracy score.

0.8.0 adds application capture with an explicit source preview and native SteamVR output. Native output is independent of a desktop window, but OCR still reads the application's PC view. GPU applications may refuse background window images, and minimized applications are unavailable. No direct headset framebuffer or VDXR/OpenXR/standalone overlay is claimed. Missing-runtime, fake ABI, rendering and lifecycle fixtures do not replace A51's headset checks.

The speech change retains up to 720 ms between words instead of splitting after about 360–380 ms. A bounded phrase uses a verified earlier pause when available rather than cutting through the final word. English filtering, silence checks and uncertain-language safeguards remain. This adds some end-of-phrase waiting time; accent recognition and general translation quality are not established by a chunking regression.

Clear generated full-screen examples passed real local OCR and English translation for Japanese, Korean and both Chinese scripts on Tokin's existing starter models. German, Italian and Spanish require additional written translation files. Their matching app-local OCR files come from the same pinned official Tesseract fast-model revision as the starter OCR files; the optional multilingual text setup retains its pinned hashes and Defender scans. Automatic OCR stays CJK; explicit Latin source selection remains required. Detailed current fixture results are recorded in the release receipt; earlier results below describe their stated historical scope.

Launcher/runtime selection with separate saved placement profiles is queued in the repository's VR roadmap. A launcher name does not establish the active overlay runtime.

The 0.7.2 patch corrects capture-menu lifetime. The menu remains owned by the dashboard until that form is disposed, and selected actions run after native menu dismissal. The existing target selection, region cancellation, capture intent and stale-session protections remain in use. The original disposed-menu exception was reproduced through native menu click messages before the fix. A separate drawing/shutdown crash was reproduced and corrected with owned-selector cleanup and closing guards.

Focused fixtures exercise native display selection, Escape, drawn-area acceptance/cancellation, repeated menu reopening, duplicate callbacks, owner shutdown, dark popup pixels, minimized Settings restoration and edit retention, reply/caption window reopening, and paused manual-read status. A 25-cycle UI walkthrough/stress fixture also covered pages, settings and reply practice without starting capture. The sidebar's native accessibility bounds and actions were verified. Native screen-selection tests use the connected display topology; a second physical monitor and a headset remain separate field tests.

## Earlier 0.7.1 results

The 0.7.1 patch replaces bright native control surfaces with application-owned dark painting. The closed and open selectors, settings tab headers and page frame, numeric buttons, field edges and native scrollbar rectangles are checked using actual rendered Windows controls. Native selection, numeric changes, text selection, tab navigation and scrollbar ranges remain under Windows control. Scrollbar appearance uses the existing scrollbars rather than a separate history or scrolling model.

The existing native UI fixtures continue to cover capture routing, transcript selection, page state, reply practice, settings, updater UI, changelog and the PC caption card. Added focused theme fixtures exercise enabled and disabled fields, an open native dropdown, dark pixels, numeric buttons, scrolling, focus and compact layouts. These fixtures create isolated windows and generated content, without starting capture or reading personal screens.

The input-frame approach was informed by Tokin Desktop Commands' earlier outline fix. The implementation is scoped to LiveTranslate windows; it does not change Windows theme preferences, security settings, registry values or system files. High contrast keeps system colors. Physical headset and day-to-day field testing remain separate from these native fixtures.

## Earlier 0.7.0 results

The 0.7.0 redesign is a native Windows Forms workspace built from the supplied Live session, Audio setup and floating-caption design references. Four persistent pages reuse the existing controls and one transcript. The updater still accepts the original signing key and public GitHub stable releases.

Native fixture checks cover capture-session routing, stale results, disconnected devices and monitors, a 1,182-caption transcript with bounded native handles, source visibility and selection retention, reply practice, settings, language search, update UI, offline changelog, page navigation, pause/resume/end, caption-window controls and long-caption paging. The fixtures create generated captions and isolate application startup; they do not listen to a microphone or capture a personal screen. Compact windows and simulated 125%, 150% and 200% scaling are layout checks rather than a claim about every real Windows DPI configuration.

The regression checks include 44 OCR-guard cases, 27 screen-engine cases, 23 GitHub feed/install cases and three public-only packaging cases. This UI release retains the 0.6.11 recognition filters; it does not establish new OCR accuracy results.

The installed 0.6.10 updater was exercised in a disposable copy against the original-key-signed 0.7.0 source update. Its real compiler and Defender checks passed. An injected commit failure restored the old fixture, and retrying the same prepared update succeeded. Runtime, model and settings sentinels retained their bytes; the actual installed app was read-only. Equal and older installs were rejected. The next-patch comparison and update UI were checked with 0.7.1, without publishing a 0.7.1 release.

Session history remains memory-only and retains the newest 180 entries. Transcript export requires an explicit file choice. Captions remain an ordinary Windows window for a compatible headset desktop view. Physical headset legibility, VRChat interaction, live audio latency and a second-PC upgrade still require Tokin/A51 field testing.

## Earlier 0.6.7 results

All 20 built-in practice combinations have a translated reply, a romanized reading and an approximate English sound cue. The four choices cover Japanese, Korean and both Mandarin writing systems. The English cues approximate the sound and do not encode every phonetic distinction.

For freeform replies, the installed multilingual model translated a test sentence into Japanese, Korean, Simplified Chinese, Traditional Chinese, French and Spanish. The reading module exercised those six recorded outputs. Four produced a reading and two kept the translation with an explicit message that a pronunciation guide was unavailable. The model vocabulary includes all 201 named target codes. Translation quality across all 201 targets and pronunciation usefulness with native speakers still require evaluation.

The native reply window passed 22 synthetic interaction checks, including a narrow window with selectable sound guidance. The fresh-install worker protocol verified 23 responses, and desktop OCR excluded the marked practice window from both screen-scan modes. Those checks used generated inputs.

The earlier field-test guide used the legacy Windows caption window and runtime pinning. Version 0.8.0 adds separate native SteamVR output as described above. Physical headset performance remains unverified. The published GitHub path still needs a live end-to-end update on a second PC.

## Earlier 0.6.6 test results

| Area | Windows test result |
| --- | --- |
| Backend regression suite | 364 tests passed with zero errors, failures or skips. |
| Starter translation models | Four of four generated CJK examples retained the scored details and repeated consistently. |
| Optional multilingual text model | Every one of 18 translations repeated consistently. Seventeen retained all scored details. The Bengali output conveyed wanting water and omitted the verb “drink.” |
| English filtering | All 3,030 pasted-text and profile combinations skipped translation. All 200 English-only screen cases stayed clear. |
| OCR placement | 34 of 36 generated mixed-language panels located the foreign text. OCR matched 27 exactly, including 11 of 12 CJK panels. Two European examples were missed. |
| Screen replay | Each of five generated panels placed one English caption, kept it stable across three scans, left the adjacent English line alone, and cleared it when the fourth scan contained only English. |
| Dashboard runtime | 26 hidden-window checks passed. Eight of those checks failed on the shipped 0.6.5 build. Cases cover display loss, source changes, restarted workers and fresh audio device lists. |
| Dashboard controls | 26 native checks passed. They exercised repeated Ctrl+Enter presses, changing languages with a request in flight, retry after failure, compact layouts and keyboard focus. |
| Transcript | 1,182 generated caption deliveries exercised the 180-entry history. A selection and its visible line survived new arrivals, eviction and source-visibility changes. Native GDI and USER handle counts stayed flat during the 1,000-entry burst. |
| Settings and language picker | 66 native checks passed, including keyboard navigation, source search, preserving edits during status refresh, update progress and compact layouts at simulated 125%, 150% and 200% scaling. Thirteen additional update-interface checks and 15 previous layout checks passed. |
| Overlay and PC VR window | 58 native checks, two replays and seven generated visual backgrounds passed. Scope included 96, 144 and 192 DPI, clipping, speech collision avoidance and long-caption reading. |
| Setup | 27 installer assertions covered repair, preserved user files, locks, rollback, shortcuts and downgrade handling. |

The older 0.6.4 continuous replay remains incomplete. The most recent saved receipt recorded 38.142 seconds, 140 trials and 147 cached phrases against a limit of 256. Automatic review stopped the run after detecting an unexpected outbound telemetry connection. It did not reach the two-hour threshold. The session tests here used generated inputs and local files. Personal screen capture, live listening and a physical headset were outside this verification.

## Earlier 0.6.5 test results

The Windows dashboard compiled with the existing .NET Framework toolchain. Thirteen updater interface checks passed. Eleven simulated GitHub transport cases and 24 existing feed/transaction tests passed. Windows verified a genuine LiveTranslate RSA-3072 signature and rejected five altered manifests. The signed GitHub feed verifies the selected stable tag, exact asset IDs, package SHA-256 and release signature before applying the existing updater transaction. Live publication and a private GitHub download require a separately provisioned private repository and CLI sign-in.

Nineteen playback checks passed. An actual installed English Windows voice synthesized a sentence into a temporary WAV: 2.43 seconds of 16 kHz mono audio, with 20,431 nonquiet samples. Device playback was simulated. No physical headset was exercised. Voice volume controls the generated voice. Per-application ducking, translation-only original audio suppression, and automatic avoidance of every acoustic echo remain open.

The 0.6.5 compatibility sweep passed all 360 cases. The four starter translation samples retained their expected details and repeated identically. The 18-language NLLB evaluation again passed 17 detail checks and all 3,030 English-input checks. The previous two-hour 0.6.4 synthetic replay has an incomplete local receipt. It is not counted as a completed stability run.

## Baseline 0.6.4 measurements

## Languages and real translation

The picker has 204 non-English source profiles. It includes 82 assigned to Asia and 56 to Europe, counting named script and regional varieties. The optional written model has 201 verified source tokens, including all 82 Asian entries and 54 European entries. Breton and Latin add European speech options. The bundled Whisper Base and optional Small tokenizers each contain 98 non-English spoken language tokens. Compatible Large-v3 weights add Cantonese. Several written profiles share a spoken language token. The picker reports local availability separately for each input.

The four included text packs were tested through the background worker without the optional model. The Simplified Chinese station and time, Traditional Chinese door instruction, Japanese train question and Korean library question all retained their tested details. All four repeats kept the first wording.

The checked NLLB text model was tested on 18 representative phrases in Simplified Chinese, Traditional Chinese, Japanese, Korean, Cantonese, Vietnamese, Indonesian, Thai, Hindi, Bengali, Tamil, Arabic, Persian, German, French, Spanish, Ukrainian and Greek. Seventeen retained every detail scored in advance. The Bengali phrase meaning “I want to drink water” became “I want some water.” All 18 repeated identically. This is a small phrase test. It does not estimate everyday accuracy across the catalog.

On the test PC, the model loaded in 1.02 s. Median first translation after load was 0.324 s. Repeating the same text through the warmed shared model took a median 0.0003 s. The four starter translations through the worker took 0.24 to 0.30 s each, including their first use, on this PC. Full voice-to-caption latency depends on recognition, buffering and hardware.

The written input filter processed 15 English examples under Auto and each of 201 written source profiles. All 3,030 combinations skipped translation. Tests also caught and corrected isolated greetings such as French “Bonjour” and Spanish “Buenos días”. Shared one-word expressions can still be ambiguous.

## Screen overlays

Real Windows OCR and the installed Tesseract models processed 36 generated bilingual images. The overlay selected the intended foreign line in 34/36 and left the adjacent English control visible in 36/36. OCR matched every source character on 11/12 starter CJK samples and 16/24 Latin-script fallback samples. Accents were a common source of differences. All 200 English-only label/source combinations stayed clear. The six evaluated Latin fallback selections were Dutch, French, German, Italian, Portuguese and Spanish. Native-language Windows or Tesseract packs can give different results.

On these cropped, generated images, warm OCR medians were 11–23 ms for the Latin fallback and 142–172 ms for CJK. Unchanged frames took around 1–3 ms. Four separate CJK recognition-and-box checks passed. A second set of 20 native OCR negative scenes stayed clear under Auto and the four starter profiles.

Seven Windows drawing scenarios covered light, dark, gradient, two textures, a busy background and a mixed recoverable region. All preserved pixels outside the caption box. Blank background pixels on flat and smooth gradient panels were preserved. Textures and animation can leave visible repairs. All seven generated watch frames passed the placement, stability and removal checks.

## Speech, interface and PC VR

The 118 audio regression tests used synthetic input and controlled recognizer output. Brief replies, English filtering, mixed inputs, stopped sessions, distinct numbers, questions and repeated wording were exercised. A Korean repeat that differed by one terminal exclamation mark now keeps the first English translation. All seven expected caption events from eight generated audio inputs appeared in order. Real microphone and headset speech accuracy, noise performance and acoustic latency have not been measured for 0.6.4.

The Windows x64 dashboard compiled. Fifteen GUI checks exercised the controls and the window was reviewed at two sizes. Twelve additional checks passed through the UI event handler. Thirty-three VR caption-window and routing checks passed, including actual capture of rendered window text, steady captions and simultaneous inputs. Headset rendering and in-game pinning still require a compatible PC VR dashboard and physical headset testing.

## Delivery and verification

The full automated backend and integration fixture suite ran 360 tests with zero errors, failures or skips. Several component counts above overlap it. The private release and update client passed 24 contract tests. The independent server suite passed seven tests with one environment-specific skip. A real Windows update transaction compiled and Defender-scanned the staged dashboard, updated an isolated installation and preserved its settings. It was exercised from the shipped 0.6.1 executable and from the 0.6.3 updater with a rebuilt test dashboard. The archived 0.6.3 dashboard source needed a duplicate local-variable name corrected to compile. The 0.6.4 dashboard and the small existing-install update include that correction.

The four NLLB files passed the new written-only setup in offline mode from staged files, including individual antivirus checks. The runtime and model-source receipts are in SOURCE-CHECKS.md. These results use generated fixtures, text and checked local model files. A physical headset, live microphone or game was not used during this release test.
