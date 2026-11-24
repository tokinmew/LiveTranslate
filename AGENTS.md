# LiveTranslate release policy

- Publish app updates only to the **public** `tokinmew/LiveTranslate` GitHub repository. Do not create or publish private releases.
- The in-app updater uses that repository's published stable release without credentials. Do not add local-manifest choices, custom update servers, bundled feeds, or fallback to a cached local release.
- Keep the signed manifest and package used internally by GitHub Releases. Preserve the existing verification key, signature checks, source-tag verification, hashes, Defender scan, and recoverable installation.
- A source push alone does not deliver an app update. Ship changed app code under a new version, push its matching source tag, and publish the assets signed by the existing owner-controlled release key. Never overwrite a published tag or release asset.
- Keep credentials, private signing keys, runtime, model weights, and user data out of Git. If the existing signer is unavailable, prepare and test the source and unsigned candidate, then report that signing is pending.

## Versioning

- Major feature or interface updates start a new minor version at patch zero: for example, 0.7.0 follows the 0.6.x series.
- Patches stay within their major update series and increment the final number: 0.7.1, 0.7.2, and so on. A patch for 0.6 remains 0.6.x.
- Preserve historical migration identifiers and runtime-format markers; those numbers are not the current application release version.
