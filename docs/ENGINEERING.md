# LiveTranslate developer and acceptance notes

## 0.6.6 interaction and release checks

The Windows tests create the actual dashboard controls with generated events. Tests cover scrolling and selecting older captions under load, the 180-entry transcript bound, device-list refresh after a worker restart, and a selected display disappearing. The monitor disconnect fixture verifies the selected capture area remains the user's choice throughout a reconnect.

The synthetic image fixtures exercise offline OCR, translation, event delivery, repeated-text suppression and clearing the overlay. Replay uses generated text panels. Speech-failure tests inject recognition results into the session. Physical listening, headset pinning and end-to-end speech recognition require separate measurements.

The existing 0.6.x application is the baseline. Retain its release numbering and supported upgrade path. English is the translation target. Traditional Chinese, Simplified Chinese, Japanese and Korean are the bundled priorities. Additional Asian and European selections show availability by speech, text and screen input.

## Data flow

| Input or operation | Production path |
| --- | --- |
| Computer or microphone audio | WASAPI capture → bounded phrase buffer → local detection/recognition → English filter → translation → first accepted wording cache → session-tagged caption |
| Screen | Selected display or region → local OCR and word boxes → source-language check → text model → background repair and English glyphs at the original coordinates |
| Pasted text | Split and identify source passages → skip English and uncertain lines → direct text pack or shared local NLLB → transcript |
| Presentation | WinForms hosts controls, transcript and desktop overlays. A separate capturable window allows PC VR runtimes to pin a caption panel. A game mirror supplies screen pixels. |
| Maintenance | The dashboard sends work to the bundled Python worker. Installers verify local assets. The update client compares versions, verifies package and file hashes, compiles the Windows UI, scans staged code with Defender and applies a recoverable replacement. |

Session IDs and stop events discard stale results. The speech cache holds up to 256 accepted phrases. Source-region tracking reuses the caption when unchanged pixels produce a slightly different OCR reading. The transcript and Windows caption renderer provide independent ways to examine recognition, wording and placement.

## Cost, privacy and distribution

| Component | Cost and data handling | Distribution note |
| --- | --- | --- |
| Whisper Base, faster-whisper, CTranslate2 | Bundled offline speech recognition and translation. No per-minute charge or hosted inference. | Original Whisper and faster-whisper carry MIT notices. Retain the runtime's accompanying licenses. |
| Four Argos text packs, Tesseract and Windows OCR | Bundled CJK text/OCR plus locally installed Windows readers. Screen frames are processed on the PC. | Check the notice for each chosen model or OS component before redistributing. |
| NLLB-200 distilled 600M int8 | Optional 601 MiB written-language download, then offline use. | CC BY-NC 4.0. This pack is for noncommercial use. |
| Whisper Small, SenseVoice and GPU options | Optional downloads. Recognition remains local. GPU support can increase installation size and VRAM use. | SenseVoice has its own model agreement. The optional NVIDIA runtime carries separate terms. |
| Windows speech synthesis | Installed local English voices can provide spoken output without a hosted TTS account. | Use Windows-provided voices on the host. Check the terms of any separately distributed voice. |
| Updates and model setup | Application updates require a published stable release in the public official GitHub repository. Translation remains local; model preparation is separate. Local update manifests, cached releases and alternate servers are not update channels. | Preserve HTTPS, the pinned release signature, file hashes and Defender verification. Report GitHub errors instead of falling back to an old local release. Keep credentials and signing keys outside the release. |

See the shipped THIRD_PARTY.md, SOURCE-CHECKS.md, WORD-DATA-LICENSES.txt and quality/MODEL-NOTICES.txt for versions and attribution. Prefer existing verified assets over adding a second ASR engine or another voice pack before measuring an actual gap. A commercial distribution needs its own review of model and component terms.

## Acceptance by phase

| Master-prompt phase | Evidence and remaining work |
| --- | --- |
| 0–2, environment, design and foundation | Hardware inventory and architecture are documented here. The existing Windows app, editable C#/Python, build and tests provide the foundation. A full benchmark of alternative ASR/TTS engines is open. |
| 3, updater | 0.6.4 private-feed tests covered real Windows compilation, scanning, in-place replacement and preserved settings; CLI and loopback contracts covered failure recovery. A live GitHub round trip needs a reachable authorized repository and a published release. Treat stable as the default. Beta/development promotion and downgrade policy require independent checks. |
| 4–6, capture and translation | Source selection, computer audio, microphone, processing queues, local translation and caption routes are implemented. Test physical device switching, overlapping speech, synthesized playback and end-to-end latency on hardware. |
| 7–8, interface and performance | The baseline passed 15 native UI and 33 VR window/routing checks. Baseline timings below cover selected operations. Validate new controls and profile the full workflow under gaming load. |
| 9–11, manual QA, packaging and release | The baseline Windows portable ZIP and updater were exercised. Verify each new release's own receipts. Physical headset playback and dashboard pinning need sign-off. Publish from a tested tagged commit after confirming repository visibility and artifact identity. |

## Reproduce the measurements

For the baseline, the local NLLB test covered 18 phrases in 18 language/script profiles. Seventeen retained every preselected detail. Median first translation after load was 324 ms. Median repeat was 0.3 ms. Loading took 1.02 s. Of 36 generated mixed-language screen frames, 34 placed a caption on the foreign line and all 36 left the adjacent English line clear. Warm cropped OCR took 11–23 ms for the tested Latin fallback and 142–172 ms for CJK. These timings exclude live source capture, speech conditioning, rendering and headset playback.

The following commands target the **original Windows test workspace**, which contains the measured models and harnesses. They can be run offline. The lightweight developer bundle and an extracted end-user ZIP may contain different directories.

```powershell
$python = (Resolve-Path 'work/captions-v04/qa-installed/LiveTranslate/runtime/python.exe').Path
& $python -I -B -X utf8 work/captions-v064/qa/measure_multilingual_text.py work/captions-v06/quality-data/speech-translation "$env:TEMP/LiveTranslate-text-results.json"
& $python -I -B -X utf8 work/captions-v064/qa_screen.py
& $python -I -B -X utf8 work/captions-v064/qa-timing/regressions.py --installer-stubs
```

For hardware profiling, use the same clip set, device format, OCR rectangle and game scene across runs. Measure at least one cold session and three warm sessions for each selected model. Record startup, time from speech end to caption, caption to first synthesized sound, missed/incorrect text and repeated wording. Record median and 95th percentile, CPU, working set, GPU utilization, VRAM, frame time and disk use. Track queue depth while speech arrives faster than playback. Compare each model's measured accuracy and delay on the same recordings.

## Manual Windows, headset and updater checks

1. Choose a local clip with known foreign speech, an English sentence, a short reply, music and a pause. Enable computer audio and confirm the selected playback meter moves. Compare source and English captions. Repeats should retain wording. English, silence and background music should leave the transcript clear.
2. Test the microphone, a call with consenting participants, separate game and chat outputs, headset disconnect/reconnect, and stopping during a model load. After stopping, verify meters settle, stale captions clear, and original audio stays audible at its prior volume.
3. When spoken captions are enabled, route synthesized English to the **same default headset endpoint being captured by WASAPI loopback**. Play one foreign utterance, stop the source, and allow playback and the queue to drain. Expect one translation, no re-translation of the English voice and no continuing queue growth. Repeat with rapid replies and simultaneous foreign speech during playback. Record any lost foreign speech. Repeat on a separate output, check voice/rate/volume, stop mid-sentence, restart and check that old queued speech stays cleared.
4. Show mixed Japanese/English text, a vertical Japanese column and two displays at different scaling. Move the source and check the English overlay covers the right word and leaves English labels alone. Pin the VR captions window from the headset dashboard when supported. Switch headset focus and confirm speech, captions, and user input continue.
5. Use disposable copies for update testing. Compare an up-to-date copy and an older one against the same feed. Test an incorrect hash, missing asset, interrupted download, failed staging and a successful update. Check the offered version, installed executable version after restart, model hashes and settings. Verify the older usable app survives a failed update. For GitHub, test access for the intended audience and confirm the selected release tag matches its manifest before promotion.
