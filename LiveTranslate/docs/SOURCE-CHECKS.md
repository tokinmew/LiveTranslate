# Download sources and checks

## 0.8.1 speech option and local diagnostics

No new runtime library or model source is introduced. The optional Small-only button delegates to the existing checked quality installer after verifying its script/scanner identities. Whisper Small's source, revision, byte counts and SHA-256 values remain pinned in that installer's original model list. Its conversion is Systran/faster-whisper-small revision `536b0662742c02347bc0e980a01041f333bce120`; model.bin is 483,546,902 bytes with SHA-256 `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`. The existing scanner checks each file before activation. Tokin's Small model was prepared through that workflow for the comparison; other PCs install it only through an explicit setup action.

Audio measurements and recognition diagnostics stay in memory. Preview recognition is an explicit local action. The app does not automatically save recordings or screenshot files. Capture opacity changes apply briefly to LiveTranslate's own windows and are restored; no Windows theme, system runtime or game files are modified. Connection profiles save app settings only.

## 0.8.0 native SteamVR and additional OCR

The native caption code uses Valve's versioned OpenVR overlay interface from the user's installed SteamVR runtime. No Valve executable or DLL is bundled or downloaded by this update. The loader locates a registered SteamVR runtime, verifies the installed DLL's Valve signature, and starts an overlay only after an explicit user action with SteamVR already running. It does not change the default VR runtime, Windows settings or VRChat files. API reference: https://github.com/ValveSoftware/openvr/blob/v2.5.1/headers/openvr_capi.h

Optional German, Italian and Spanish OCR data come from the official Tesseract fast-model repository at the same pinned commit as the starter models: https://github.com/tesseract-ocr/tessdata_fast/tree/65727574dfcd264acbb0c3e07860e4e9e9b22185 . The app pins each byte count, SHA-256 and Git blob identity in `backend/extra_ocr_models.py`, verifies the downloaded bytes and runs the existing checked Microsoft Defender scanner before activation. These are app-local data files; Windows language packs are not installed or modified.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| deu.traineddata | 1,525,436 | 19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d |
| ita.traineddata | 2,701,314 | b8f89e1e785118dac4d51ae042c029a64edb5c3ee42ef73027a6d412748d8827 |
| spa.traineddata | 2,294,433 | 6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464 |

Written translation continues to use the existing checked NLLB conversion and license described below. Its files and all three additional OCR files were prepared on Tokin's PC through the checked installers for testing. Each other PC needs its own model setup. Native headset output remains a physical field-test requirement.

## 0.6.7 reply practice

The starter examples and pronunciation code ship in the app. Custom replies use the existing optional multilingual written model. Japanese and Mandarin reading tables are derived from the previously reviewed JMdict and CC-CEDICT data sources. See the headers in **backend/reply_ja_data.py** and **backend/reply_zh_data.py** and the upstream notices in **WORD-DATA-LICENSES.txt**.

## 0.6.6 interface and caption fixes

The interface uses Windows Forms, system fonts and graphics drawn by the app. This release reuses the existing model and runtime distributions. It introduces no third-party download, web font, JavaScript library or paid service.

## 0.6.4 language expansion

This release adds first-party code and reuses the reviewed local runtime and model payloads. No new third-party executable, DLL, model or font was downloaded for this build. PC VR captions use a native window drawn by the app. No Valve library is loaded or included for this feature.

1. **Origin.** The underlying text model is Meta's NLLB-200 distilled 600M, licensed CC BY-NC 4.0. The exact int8 conversion is from the community publisher JustFrederik. Its Hugging Face repository links to the underlying Meta model. The quality installer pins conversion revision `302d78f00e6fdb50a1064059df7c392b735e9d05`.
2. **File identity.** All 13 starter model files matched their recorded sizes and hashes. The four optional NLLB files matched the original release's individual SHA-256 pins. The conversion publisher's file page independently displays the 622,595,991-byte weights' SHA-256 as `ed1beaf75134de7505315a5223162f56acff397eff6b50638a500d3936fe707b`. The existing portable dependency ZIP was checked against its historical SHA-256; the release builder reopens the new ZIP and hashes every member.
3. **Independent site reputation.** ScamAdviser displayed “Very Likely Safe” for huggingface.co. AdGuard reported no Google or Yandex Safe Browsing listing. Gridinsoft showed 79/100 with a mixed assessment and a malicious verdict in its external-provider list. PCrisk showed 0/93 URL threat detections for github.com in its November 14 report. These reports describe hosts and are date-specific.
4. **File scanning.** The local Microsoft Defender command-line scanner returned an explicit clean verdict for the starter text archives, Whisper Base folder, starter OCR files and all four local optional NLLB files. The written-language installer was also exercised offline using a separate copy of the exact four files, requiring a per-file Defender scan before activation. Hugging Face documents scanning repository files under 2 GB with ClamAV. An exact-hash lookup of the public weights did not yield a readable VirusTotal or MetaDefender verdict here. Microsoft Defender was the local file-scanning engine confirmed for this build.

- Model owner and license. https://huggingface.co/facebook/nllb-200-distilled-600M
- Conversion and pinned weights. https://huggingface.co/JustFrederik/nllb-200-distilled-600M-ct2-int8/blob/302d78f00e6fdb50a1064059df7c392b735e9d05/model.bin
- Repository malware-scanning policy. https://huggingface.co/docs/hub/en/security-malware
- Independent site reports. https://www.scamadviser.com/check-website/huggingface.co and https://reports.adguard.com/en/huggingface.co/report.html and https://gridinsoft.com/online-virus-scanner/url/huggingface-co
- GitHub host report. https://scanner.pcrisk.com/scan-results/github.com

Earlier reviews of the retained files follow.

Reviewed November 18, 2026. The following checks cover the origins, independent reputation reports, published file identities, and the local antivirus decision. A site's reputation is a snapshot. A clean antivirus result applies only to the file that the scanner examined.

## Model origins

| Files | Origin and identity |
| --- | --- |
| Five Tesseract OCR files | The Tesseract project identifies its fast model repository. The GitHub release page shows a verified signature on the 4.1.0 tag. The manifest pins the commit, filename, byte count and individual Git blob ID. |
| One multilingual Whisper model and three companion files | SYSTRAN publishes the CTranslate2 conversion. The manifest pins the weights' SHA-256. Version 0.4 also pins the Git blob identities, byte counts and SHA-256 values of all three companion files after comparison with the tree at the same revision. |
| Four Argos text models | Community mirrors on Hugging Face host the four complete language archives. The manifest pins each mirror revision, file length and published SHA-256. The byte-for-byte relationship to the original Argos publisher's archives is unconfirmed. A second mirror lists the same Simplified Chinese digest. |

The exact file pages are in config/model-sources.json. Hugging Face documents running ClamAV on repository files under 2 GB at each commit. The file page for the speech model displayed its Safe badge. The archived text-file evidence is recorded individually in the manifest.

https://tesseract-ocr.github.io/tessdoc/Data-Files.html
https://github.com/tesseract-ocr/tessdata_fast/releases/tag/4.1.0
https://github.com/SYSTRAN/faster-whisper
https://huggingface.co/Systran/faster-whisper-base
https://huggingface.co/docs/hub/en/security-malware
https://huggingface.co/docs/hub/en/models-downloading

## Independent origin checks

| Origin | Evidence observed |
| --- | --- |
| GitHub and its raw-file host | PCrisk recorded 0 of 93 URL threat engines flagging github.com on November 14 and 0 of 93 flagging raw.githubusercontent.com on November 13. These scans covered the origins. |
| Hugging Face | ScamAdviser rated the domain Very Likely Safe. AdGuard reported no Google or Yandex Safe Browsing listing. Gridinsoft scored it 79/100 and displayed one malicious verdict among 27 external sources in its November 5 check. |
| Python and PyPI | The Python Software Foundation publishes its Windows releases and lists its package index on its infrastructure status page. PCrisk recorded 0 of 91 threat engines flagging python.org on June 28 and 0 of 91 flagging pypi.org on June 16. These reports cover earlier dates. |
| Python package files | PyPI's JSON API identifies each release file by name, size, URL and SHA-256. ScamAdviser assessed files.pythonhosted.org as likely legitimate. Gridinsoft also gave the file host a high trust score. |

https://scanner.pcrisk.com/scan-results/github.com
https://scanner.pcrisk.com/scan-results/raw.githubusercontent.com
https://www.scamadviser.com/check-website/huggingface.co
https://reports.adguard.com/en/huggingface.co/report.html
https://gridinsoft.com/online-virus-scanner/url/huggingface-co
https://www.python.org/downloads/windows/
https://status.python.org/
https://scanner.pcrisk.com/scan-results/python.org
https://scanner.pcrisk.com/scan-results/pypi.org
https://www.scamadviser.com/check-website/files.pythonhosted.org
https://gridinsoft.com/online-virus-scanner/url/files-pythonhosted-org
https://docs.pypi.org/api/json/

## What happens on your PC

The model downloader restricts HTTPS destinations and redirects, checks the file size and digest, and calls Microsoft Defender for each file. The verdict must identify that exact path as clean. A mismatch, blocked connection or unavailable scan leaves the item unapproved. The results are in model-test-results/model-file-checks.json. The downloader calculates SHA-256 locally even for OCR files identified upstream by Git blob SHA-1.

Reputation reports above cover the listed service origins. The allowed Hugging Face content-delivery addresses are part of the service's delivery network. The pin and local antivirus gate apply to the final bytes regardless of the allowed delivery address.

The model test runner starts after the files pass and the runtime is ready. It uses generated example images and local speech recordings. Four prerecorded WAV files ship with this version. Each recording was matched to the exact repository revision, size and Git object ID and scanned with Microsoft Defender. The per-file SHA-256 values are in fixture-tools/audio/manifest.json. The upstream source and license accompany the recordings. Actual model output appears in model-test-results/report.txt after inference runs.

Runtime setup checks the Python and pip bootstrap archives against fixed SHA-256 values and scans them with Defender before extraction. It checks each remaining dependency wheel against the exact filename, size and digest in its official PyPI release record and scans it before installation. Optional language archives that you import yourself use the app's local import feature and have a separate provenance.

## 0.5 short-voice test inputs

The release reuses the checked offline language models. Independent tests also used 30 prerecorded human words or replies. These additional recordings stay outside the downloadable app. Their archive entries and publisher transcripts were cross-checked at the repository revisions below. Each of the 30 downloaded files matched its recorded Git object and byte count. A SHA-256 digest and the result of a local Microsoft Defender scan were recorded before audio decoding. The GitHub host was also checked with PCrisk (0 of 93 detections in its November 14 report) and TrustDepth (98/100 at review).

- Japanese recordings. https://github.com/tofugu/japanese-vocabulary-pronunciation-audio/tree/9725e0e7d628ab616e8b14e126d3daa33eba8d36
- Mandarin recording credits. https://github.com/leoborja/manman/blob/7115fa02fd351caade20679334c764ea602cdd89/audio/nativo/CREDITS.md
- Korean speech corpus and transcripts. https://github.com/deeplyinc/Korean-Read-Speech-Corpus/tree/1c9cdb8ca1ba79bf982c97b16fb40657420c9cba
- Hosting checks. https://scanner.pcrisk.com/scan-results/github.com and https://trustdepth.com/check/github.com
