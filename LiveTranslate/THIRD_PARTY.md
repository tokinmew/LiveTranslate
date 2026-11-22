# Third-party software

The optional speech setup includes Whisper Small, SenseVoiceSmall and NLLB-200 distilled 600M. NLLB uses a noncommercial license. The installer supplies model authors, revisions, license references and checks in **quality/MODEL-NOTICES.txt**. The language-specific word data are attributed in **WORD-DATA-LICENSES.txt**.

Live Translate includes a custom Windows UI, Python integration, setup scripts and editable source. The complete offline edition also includes the runtime, model archives and upstream license notices. The compact update can reuse an existing installation or download missing components through Setup. The upstream licenses accompany their components.

| Component | Use | Upstream |
| --- | --- | --- |
| CPython and pip | Private app runtime and installer | https://www.python.org/ and https://pip.pypa.io/ |
| Whisper and faster-whisper | Multilingual speech to English | https://github.com/openai/whisper and https://github.com/SYSTRAN/faster-whisper |
| CTranslate2 and SentencePiece | Local text inference and tokenization | https://github.com/OpenNMT/CTranslate2 and https://github.com/google/sentencepiece |
| Argos package index and models | Direct source-to-English model files | https://github.com/argosopentech/argospm-index |
| py3langid and OpenCC | Text language identification and Chinese script detection | https://pypi.org/project/py3langid/ and https://pypi.org/project/opencc-python-reimplemented/ |
| PyAudioWPatch and PortAudio | Windows microphone and loopback capture | https://github.com/s0d3s/PyAudioWPatch |
| NumPy and SciPy | Audio samples and resampling | https://numpy.org/ and https://scipy.org/ |
| MSS and Pillow | Screen capture and image handling | https://github.com/BoboTiG/python-mss and https://python-pillow.org/ |
| Tesseract, Leptonica, tesserocr and pytesseract | OCR library and optional executable integration | https://pypi.org/project/tesserocr/ and https://github.com/madmaze/pytesseract |
| tessdata_fast | OCR recognition weights | https://github.com/tesseract-ocr/tessdata_fast |

Check the license included with each model before redistributing downloaded weights.

The new caption overlay uses Windows Forms and native Windows window APIs. The English screen-text check uses Windows.Media.Ocr with an installed English OCR language.

The four small QA recordings in fixture-tools/audio come from the sample directory of wudale/whisper-asr-server at revision f86a51a04e5c9e6b82dc9f22c01ada4cb8c40c5f. The original copyright notice and license are included in fixture-tools/audio/LICENSE.txt. The adjacent manifest contains the source URL, byte count and SHA-256 for each file.

https://github.com/wudale/whisper-asr-server/tree/f86a51a04e5c9e6b82dc9f22c01ada4cb8c40c5f/samples


The separate Korean dialogue installer obtains the pinned Whisper Large-v3 files and the original NVIDIA cuBLAS wheel. The included terms and source checks are in **dialogue/NVIDIA-License.txt** and **dialogue/GPU-SOURCES.md**.
