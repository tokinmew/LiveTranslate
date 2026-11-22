# LiveTranslate release owner

The development baseline is 0.6.4. Version 0.6.5 preserves the existing model directory and adds signed stable GitHub updates, optional spoken English and a per-user setup kit. Use the small application update for a prepared install.

## Publish the prepared release

Open **publisher/Publish GitHub release.cmd** on Windows with the free GitHub CLI installed and signed into **tokinmew**. Select the signed feed supplied with this kit. Preview shows the proposed repository and artifacts before publication. The project repository must be private. The app can check the original local feed independently of GitHub.

The **LiveTranslate-source.bundle** file contains the local development history. Run `git clone --branch main LiveTranslate-source.bundle LiveTranslate-source` to open it. The publisher verifies the tagged source against the signed package before pushing the tag to the dedicated private repository. An existing main branch is preserved. The publisher README describes the sequence and retry behavior.

## Build a future release

Edit the app under **LiveTranslate**. Update both Windows assembly version attributes in **ui/Program.cs**. The dashboard reads the compiled version and the package publisher checks both attributes against the requested release number. Build with **Build.cmd** from the app folder. The base release installer provides the pinned Python runtime, model files and third-party licenses.

From the project root, use the app's prepared Python to run `tools/publish_update.py --app LiveTranslate --version X.Y.Z --feed release`. Sign the manifest with **publisher/Sign-Release.ps1** and the existing LiveTranslate owner key. Open the GitHub publisher, review the offline preview, and use a new tag when release contents change. Reuse the same signed files when retrying an interrupted upload.

The signing key for these builds is held locally at **work/LiveTranslate-owner-signer/LiveTranslate-release-v1.dpapi** under the original Windows workspace. Windows protects it for the current user. Keep a private recovery backup of the key and its Windows user profile. A different signing key requires a deliberately distributed trust update. The ZIP and Git history contain only the pinned public key.

GitHub Free supports private repositories. This workflow runs compilation, signing and publishing on the owner's PC and uses no hosted Actions runner. The noncommercial terms on the optional NLLB model still apply independently.

## Verification for this version

The published source and release-asset API contracts were checked against GitHub's documentation. PCrisk's November 14 check reported 0/93 threat-engine detections for github.com, ScamAdviser displayed “Very Likely Safe,” and AdGuard reported no Google or Yandex Safe Browsing listing. These results concern the website. The local Windows files were checked separately. The code uses installed Windows SAPI and CryptoAPI. No new third-party binaries or AI weights were downloaded for 0.6.5.

The final 0.6.5 release passed real installer and uninstaller checks under a disposable profile, 360 application regression cases, and signature and asset corruption rejection. Actual 0.6.4 and simulated private GitHub update paths both compiled with Windows, scanned the staged files with Defender, applied 103 source files, preserved settings and a checked Japanese OCR file, and recognized the newly installed version. The new English voice synthesized a 2.43-second sentence locally. Physical headset routing and live private publication require separate checks.

- GitHub release APIs and plans. https://docs.github.com/en/rest/releases and https://docs.github.com/en/get-started/learning-about-github/githubs-plans
- Site reports. https://scanner.pcrisk.com/scan-results/github.com and https://www.scamadviser.com/check-website/github.com and https://reports.adguard.com/en/github.com/report.html
