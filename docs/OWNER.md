# LiveTranslate release owner guide

The **feed** directory holds the signed Windows update. **LiveTranslate-source.bundle** contains the editable source and preserved release tags. The public key embedded in LiveTranslate verifies the release manifest. The manifest identifies the package by version, size, and SHA-256. The publisher compares every packaged source file against its release tag before publication.

Use **FIELD-TEST.md** to record desktop results on Tokin's PC and physical PC VR results with A51's headset. A51 owns headset validation. Desktop work can proceed independently.

## Preview or publish

1. Extract the developer ZIP. With a prepared LiveTranslate installation, open **publisher/Publish GitHub release.cmd** and select **feed/latest.json** and the app’s **runtime/python.exe** when asked. To run the offline preview directly, use the first command below from the extracted kit.
2. The preview checks the signature and matching tag. Publishing requires Git for Windows and the free GitHub CLI signed into **tokinmew** with write access to the public **tokinmew/LiveTranslate** repository. The publisher refuses private destinations. For initial creation only, `--init-public` explicitly permits creating that public repository.
3. Publication uploads both assets to a draft, downloads them by their GitHub IDs, verifies their bytes and source tag, and promotes the draft. It then checks GitHub’s latest stable release. On an interrupted upload, repeat with the identical signed files. A conflicting tag or asset requires a new release version or owner review. The publisher seeds main when creating an empty repo and preserves an existing main branch.
4. In the app, open **Settings > Updates** and select **Check for updates**. Starting with 0.6.10, the only update source is the official public GitHub stable release. Readers need neither an account nor GitHub CLI. Local manifests, custom sources, cached feeds and unpublished builds cannot supply an app update. Network or publication errors are reported without a local fallback. The app prepares a new dashboard with the Windows compiler and scans the staged files with Microsoft Defender before installation.

```powershell
& 'C:\path\to\LiveTranslate\runtime\python.exe' -I -B publisher/github_publish.py --dry-run --feed feed --source-bundle LiveTranslate-source.bundle
git clone --branch main LiveTranslate-source.bundle LiveTranslate-source
```

## Rebuild or test locally

From the cloned source directory, open **LiveTranslate/scripts/Build.cmd** to compile the Windows app. Use the prepared Python runtime when running the Python utilities. The portable build helper accepts **--app LiveTranslate**, **--base** pointing to the original verified 0.6.7 Windows Test ZIP, and **--output** pointing to a new ZIP. The original archive supplies the checked runtime, offline models, and third-party notices.

The release includes these offline checks.

- **qa/Check-WindowsUI.ps1** builds the dashboard and runs synthetic Windows control, transcript, settings, and caption readability checks. It saves test images under a fresh temporary folder. The tests use generated text and controls and leave capture inputs closed.
- **qa/check_reply_worker.py** checks the offline starter replies, freeform replies and incoming English suppression. Pass the prepared model directory that contains **nllb-600m-int8**. The Windows control suite also exercises the separate reply practice window.
- **qa/live_model_screen.py** runs the screen watcher on generated Asian-language panels. **qa/qa_screen.py** measures word placement and English-only filtering across Asian and European examples. Set **LIVETRANSLATE_TEST_DATA** to the prepared app’s **data** folder and run these with its bundled Python. The broader test uses the additional tested OCR languages.
- **installer/Test-Installer.ps1 -Python PATH** installs, upgrades, repairs, and uninstalls a generated package under a disposable directory. Its checks include model and settings retention, active model/setup locks, and user-owned shortcuts.
- **publisher/test_github_publish.py** simulates release upload, cancellation and retry, changed assets, wrong accounts, and downgrade handling in memory.
- **qa/upgrade_e2e.py** applies the 0.6.8 feed to two disposable 0.6.7 fixtures using a local folder and simulated private GitHub responses. For that archived test, provide the original 0.6.8 feed, **--old-app** pointing to the built 0.6.7 app, **--old-portable** pointing to its original Windows Test ZIP, and **--ocr-model** pointing to a checked Japanese OCR file if needed. The harness verifies the native file version, source hashes, retained settings and model, and the official signature.

## Prepare another update

1. Edit the app under **LiveTranslate**. Set both assembly version attributes in **ui/Program.cs** and add the release entry to **ui/ReleaseHistory.cs**. If distribution scripts, configuration or guides change, regenerate the migration catalog with `python tools/build_layout_sources.py` before compiling. Build and test the application and create a signed feed for the new version.
2. In the source checkout, run the bundled Python with `tools/publish_update.py --app LiveTranslate --version X.Y.Z --feed release`. Run **publisher/Sign-Release.ps1** with the existing release key. Keep the private key on the owner’s Windows profile and protect its recovery backup. The developer ZIP contains only the verifier and public key.
3. Commit the matching sources, tag the exact release commit with **vX.Y.Z**, then run `git bundle create LiveTranslate-source.bundle refs/heads/main refs/tags/vX.Y.Z`. Keep earlier tags in a complete archival bundle by passing their refs as well. Supply the new signed feed and source bundle to the offline preview before publishing.
4. Push the exact release commit and its version tag to the public repository, then publish the two signed assets using the checked publisher. A source push alone is not an app update. Never publish unsigned assets, reuse a version for changed bytes, replace existing tags, or change the release key to bypass signing.
5. For a full per-user Windows installer, build the portable application and run `installer/desktop-setup/Build-DesktopSetup.ps1` with its portable ZIP, release version, icon and Python runtime. Starting with 0.6.10, portable builds and installers do not contain a local update feed. `tools/build_small_update.py` remains an archival recovery tool for older clients, not an update channel in the current app.

Microsoft Defender runs on the newly prepared local update. The publisher also verifies asset digests and the official signature. No release, credentials, or test fixtures need to leave the machine for the offline preview or synthetic tests. Consult the included app guide for the licenses applicable to each optional model.
