# LiveTranslate 0.6.4 test results

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
