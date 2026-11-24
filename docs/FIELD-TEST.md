# LiveTranslate field test

Tokin owns Windows desktop testing this week. A51 is the main user and owns the physical headset test. A51's headset run is **pending**. The PC VR caption window is implemented. The project has recorded Windows window tests and generated replays. In-headset pinning, readability and live VRChat latency still need a headset result.

Record the app version, display scale, audio output name and test case. For each miss, note the source, expected meaning, actual caption and approximate time until it appeared or cleared. Keep tests on your own sample text or a consenting test partner's scripted lines.

## Tokin · Windows

1. **Place a caption.** On your fresh installation, enable Caption overlay, choose Auto, leave Auto listen off and watch a small area in a text editor. Use the two lines below in a large font. Expect one caption conveying when the next train is, directly over the Japanese line. The English line should stay visible.

   ```text
   次の電車は何時ですか？
   Press here to continue.
   ```

2. **Change the source.** Leave the same two lines visible for several scans. Expect stable wording and position. Replace the first line with `図書館はどこですか？` (“Where is the library?”). Check that it updates. Remove the Japanese line and check that the overlay clears. Repeat at your usual display scale, and try a subtitle moving across a textured background.
3. **Try a different language.** Test `请把门关上。` (Simplified Chinese), `請把門關上。` (Traditional Chinese) and `도서관은 어디에 있나요?` (Korean) with Auto. The Chinese lines ask to close the door. The Korean line asks where the library is. For French or Spanish screen text, select the source and confirm Screen is ready in the language picker.
4. **Separate speech from screen.** Turn Watch screen off. Choose Computer audio, select the playback device your game uses and enable Auto listen. Play a known foreign sentence, a brief reply, and an English control, then repeat with music. Note missed words, English captions triggered by English speech, and delay from the end of each line.
5. **Practice a reply on a fresh install.** In Reply practice, try the included “Please say that again” or “Hello” with Japanese, Korean and Mandarin Chinese. Check the meaning of the translated words and the separate pronunciation line. Change targets and make sure both lines update. Ask a speaker of the target language whether they recognize the phrase when you read the guide aloud. For Mandarin, check whether the tone marks help. After installing the optional written pack, test a custom request such as “Where is the library?” If its reading is unavailable, expect a clear message and the translated words to stay available. Record translation accuracy and pronunciation usefulness separately.

6. **Check for updates.** Open Settings, Updates and select Check for updates. Updates come from the official public GitHub stable release. After installing, record the displayed version, confirm settings and installed models were retained, restart and check again. It should report the installed release as current. Connection errors must not fall back to a local feed.
7. **Challenge screen recognition.** With no foreign text present, watch browser and app toolbars, light/dark menus, and game clothing or patterned scenery. Clear history first and note any new SCREEN entry. Then introduce known Japanese, Chinese and Korean text into the same area: verify the full source and meaning, not just whether a caption appeared. Test short labels separately with Auto/full display and an explicitly selected area or language. An icon and a one-character label can look identical; automatic reading conservatively ignores ambiguous isolated symbols.

## A51 · PC VR headset

1. Launch PC VRChat and confirm the Windows playback device carrying the other player's voice. In LiveTranslate choose that device under Computer audio, enable Auto listen and leave Watch screen off for the voice test.
2. Open **VR captions**. From the headset's PC desktop/window view, select **LiveTranslate VR captions** and pin it if the runtime offers pinning. Return to the game. Record the headset and runtime, whether captions remain visible, whether they block faces or menus, and whether game input keeps focus.
3. Ask a consenting partner to use a known greeting, a brief reply, a number and a full sentence. Alternate foreign and English lines. Repeat with world music and then overlapping speech. Record meaning, misses, English false positives, and whether the caption arrived before the next turn.
4. Test screen translation separately on text visible in the game's desktop mirror. Select that monitor or a small region. Verify what appears in the VR caption window while moving your head. Record issues with mirror capture separately from voice issues.

Tokin can complete the desktop section while A51 arranges the headset session. The desktop results can isolate OCR and model errors before the same samples reach VR.
