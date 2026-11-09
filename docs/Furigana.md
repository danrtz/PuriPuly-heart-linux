# Japanese furigana

Enable **Japanese Furigana** in Settings → Overlay. It is off by default and persists across restarts. The CLI setting is `overlay.furigana.enabled`.

Japanese original captions and Japanese translations keep their normal text. The local tokenizer supplies hiragana readings, which the desktop and Linux VR renderers place below the corresponding kanji words. The Agent Chat history view uses the same setting for both Japanese originals and translations, including messages already in the session. Kana endings stay outside the annotated kanji: 食べる gets た under 食. English captions are unchanged. Readings are presentation metadata; they do not alter translation input, stored conversation text or VRChat chatbox messages.

Remove any custom “hiragana only” translation-prompt section if you want translated Japanese to contain kanji. The app cannot add kanji back to text that a model already returned entirely in hiragana.

Readings use fugashi 1.5.2 and UniDic-lite 1.0.8 locally. There is no extra model request or network lookup. The bounded cache retains up to 512 caption/language pairs in memory, and conversion is run outside the application event loop. A dictionary failure preserves the caption and marks its kanji with ？ instead of breaking output. Unknown readings use the same marker.

This guarantees that Japanese captions go through the annotation stage while enabled. Dictionary readings can still be wrong for names or ambiguous words. A reading-correction editor is not included. Hiragana and katakana without kanji do not need annotations.

Both caption renderers reserve space below the base characters, wrap between annotation units, and preserve the normal caption lifetime. Readings use 72% of the base-character size, roughly 50% larger than the initial implementation. The desktop renderer scales the characters to fit the existing caption regions; use the desktop caption size or VR text-size control to enlarge the whole caption. History readings are at least 15 logical pixels and wrap without truncating the conversation. History conversion runs in a background thread and reuses unchanged message controls. Linux VR rendering retains the existing caption colors and calibration. Windows native rendering does not yet draw the optional ruby metadata.

Validation uses generated captions, the actual desktop rendering controls, native image renders, serialization and presenter tests, restart persistence, and isolated GPU recognition/translation probes. Synthetic rendering is not a headset visibility check.

## Checked build

The Linux integration is based on upstream dev `005bb36a` (2.10.0), with the fork's prior changes retained. Final Python validation passed 11,446 tests, with 97 integration/platform-gated skips. An earlier four-worker run hit an existing one-second SmartTurn preload timeout; that test passed alone and the complete two-worker rerun passed. Native validation passed 224 overlay tests and 11 ASR-worker tests. Ruff, Black, dependency-lock validation and TypeScript checking also completed.

Real local GPU probes produced authoritative speech-recognition finals for both channels and a synthetic Gemma translation, using the existing Qwen 1.7B Q6 and Gemma E4B Q4 models. These probes do not record the microphone or publish to VRChat. They verify inference and cleanup, not recognition accuracy. The GUI setting was rendered and toggled, the reading placement was inspected in desktop/native renders, and the saved setting survived a real host restart.

The history/readability follow-up passed 349 affected Python checks and all 224 native overlay checks. Generated conversation-history, desktop and native previews were inspected for reading placement and wrapping. The full Python suite above belongs to the initial integration; it was not rerun for this presentation-only follow-up.
