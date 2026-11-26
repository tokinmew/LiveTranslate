# VR capture and overlay roadmap

Updated 2026-11-25 following the 0.7.2 field report. A51 uses Quest 3S through Virtual Desktop. Tokin handles PC development/testing; A51 usually tests one evening per day, sometimes with gaps of one or two days.

## Current 0.8.0 work

- Native SteamVR caption output independent of a desktop window and monitor count.
- Application capture target and explicit preview; OCR statuses distinguish an unavailable source from no confirmed foreign text.
- Longer pauses retained during speech capture, with existing English and silence safeguards.
- German, Italian and Spanish written translation and matching OCR preparation alongside the four starter Asian profiles.
- Field retests remain required; developer fixtures do not establish accuracy with actual speakers or a physical headset.

## Next feature: launcher and runtime profiles

Requested by Tokin: let users choose their VR launcher/connection and retain suitable overlay placement for that setup.

1. Distinguish the connection/launcher (Virtual Desktop, Steam Link, Meta Quest Link) from the active rendering runtime (SteamVR versus OpenXR/VDXR). Detect the running runtime when possible and show it plainly.
2. Save caption width, distance, vertical position, and eventually anchoring separately for each selected setup. Restore the user's adjustments when changing profiles; do not infer headset resolution or a universal layout from the launcher name.
3. Use SteamVR's native overlay backend for supported SteamVR sessions. Add a separately validated OpenXR/VDXR overlay path before offering those sessions as supported. Never silently switch the system's default runtime or inject into VRChat to make a selector appear functional.
4. Explain unsupported setups with a working next step. Standalone VRChat requires a separate headset solution; a Windows overlay cannot imply standalone support.

Tokin can validate profile selection, saved settings, runtime detection, missing-runtime errors and caption rendering on PC. A51 should first test the existing Quest 3S/Virtual Desktop/SteamVR path on one monitor, then another available runtime in a later short evening session. Preserve prior test results and assign only the affected retests.

Keep this queued behind capture reliability and the first native-overlay headset retest. A connection selector alone does not complete multi-runtime support.
