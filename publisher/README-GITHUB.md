# LiveTranslate private release publisher

This owner tool publishes a stable Windows update to **tokinmew/LiveTranslate**. It uses the existing GitHub CLI sign-in, Git for Windows and the Python runtime supplied with LiveTranslate. Publishing happens on your PC. It requires no GitHub Actions runner, hosted server or paid API. The local GitHub CLI session must have write access and be signed in to github.com as **tokinmew**. Keep the application source bundle one directory above the publisher scripts.

## Publish the supplied signed feed

1. Extract the publisher ZIP. Open **Publish GitHub release.cmd**. If asked, choose the release folder's **latest.json** and then **python.exe** inside your prepared LiveTranslate app's **runtime** folder.
2. The console prints the version, SHA-256 and size of each release asset. Choose **Yes** to publish to the dedicated private repository. If it does not exist and the GitHub account can create it, the publisher creates it with private visibility.
3. The publisher verifies the signed manifest and checks every update file against the corresponding file under **LiveTranslate/** in the bundle's exact Git tag. An empty private repository receives the release commit on **main** and the original tag in one atomic push. An established repository receives only the matching tag and its source history. An existing **main** stays in place, and a different existing release tag stops publication.
4. The publisher uploads the numbered package and **latest.json** to a draft and reads each asset back by its GitHub ID. After verifying the bytes and remote source tag it publishes the stable release, then verifies the latest stable endpoint. The app's GitHub update source is **https://github.com/tokinmew/LiveTranslate**. Readers need access to this private repository.

After an interruption, run the same publisher with the same signed bytes. It checks the draft, reuses matching assets and uploads missing assets. A changed asset or an incomplete previously published release stops publication. Use a new version for changed release contents. GitHub Actions and third-party update services are outside this release path.

## Prepare a future version

Generate the versioned application package and **latest.json** with **publish_update.py** from the LiveTranslate release server kit. Use your dedicated release signing key and **Sign-Release.ps1** to authorize that manifest. Keep the key in its owner-only location. Commit the corresponding editable app source under **LiveTranslate/**, tag the verified release commit, then make a complete bundle with **main** and that tag. For example, run `git bundle create LiveTranslate-source.bundle refs/heads/main refs/tags/v0.6.5` in the source repository for version 0.6.5. Include only sources and history suitable for the private repository. The public verification key can travel with the app.

With the app's bundled Python, pass **--feed PATH --dry-run** to **github_publish.py** for an offline preview. Add **--source-bundle BUNDLE** to select another bundle. The default is **../LiveTranslate-source.bundle**, relative to the publisher script directory. Use **--feed PATH --publish** to publish into the existing private repo. Adding **--init-private** allows creation of the dedicated private repo when missing. Git obtains credentials from the existing GitHub CLI session for the fixed github.com HTTPS destination.
