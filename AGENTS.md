# LiveTranslate release policy

- Publish app updates only to the **public** `tokinmew/LiveTranslate` GitHub repository. Do not create or publish private releases.
- The in-app updater uses that repository's published stable release without credentials. Do not add local-manifest choices, custom update servers, bundled feeds, or fallback to a cached local release.
- Keep the signed manifest and package used internally by GitHub Releases. Preserve the existing verification key, signature checks, source-tag verification, hashes, Defender scan, and recoverable installation.
- A source push alone does not deliver an app update. Ship changed app code under a new version, push its matching source tag, and publish the assets signed by the existing owner-controlled release key. Never overwrite a published tag or release asset.
- Keep credentials, private signing keys, runtime, model weights, and user data out of Git. If the existing signer is unavailable, prepare and test the source and unsigned candidate, then report that signing is pending.
