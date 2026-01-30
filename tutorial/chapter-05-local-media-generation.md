# Chapter 5: Local Media Generation

This chapter covers the third stage of the pipeline — converting text into audio files. The TTS module takes two text strings (the vocabulary word and the LLM-generated example sentence) and produces two `.mp3` files that will be embedded in the Anki flashcard. The focus here is on how edge-tts works, the async-to-sync bridge required to use it from a synchronous pipeline, filename normalization for cross-system compatibility, and the file path conventions that Anki requires for media linkage.

## edge-tts

### What It Is

`edge-tts` is a Python package that interfaces with Microsoft Edge's online text-to-speech service. It uses the same WebSocket-based protocol that the Edge browser uses for its built-in Read Aloud feature. The service is free, requires no API key, and supports a wide range of voices across many languages.

For Japanese, the service provides several neural voices. Neural TTS voices are trained on deep learning models rather than concatenated from pre-recorded speech fragments, which produces more natural prosody, pitch accent, and rhythm — all of which matter significantly for Japanese language learning.

### Why Not Fully Local TTS?

The chapter title says "local media generation," and most of this project's architecture avoids network calls. edge-tts is the exception — it sends text to Microsoft's endpoint and receives audio back. This is a pragmatic trade-off.

Fully local TTS options for Japanese exist. Projects like VOICEVOX and Style-BERT-VITS2 can run entirely on your machine and produce high-quality Japanese speech. However, they require:

- Downloading and running a separate inference server (VOICEVOX is ~1–2 GB)
- GPU resources that compete with LM Studio for VRAM
- Additional setup that varies by platform

edge-tts requires none of this — it is a single `pip install` with no system dependencies. The data exposure is minimal: the only text sent to Microsoft's servers is the vocabulary word and one example sentence, with no user-identifying information attached. For a language learning tool, this is an acceptable compromise.

If local-only operation is a hard requirement for your use case, the module's interface makes substitution straightforward. `generate_audio(text, filename)` takes a string and returns a file path — any TTS backend that can write an audio file to disk is a drop-in replacement. The rest of the pipeline does not know or care how the audio was produced.

### Available Japanese Voices

edge-tts provides multiple Japanese voices. The voice is specified by a locale-and-name string:

| Voice ID | Gender | Characteristics |
|----------|--------|----------------|
| `ja-JP-NanamiNeural` | Female | Clear, natural prosody. Default for this project |
| `ja-JP-KeitaNeural` | Male | Slightly lower pitch, standard NHK-style pronunciation |

Our module uses `ja-JP-NanamiNeural`. To change the voice, modify the `VOICE` constant at the top of the module. You can list all available voices programmatically:

```python
import asyncio
import edge_tts

async def list_voices():
    voices = await edge_tts.list_voices()
    for v in voices:
        if v["Locale"].startswith("ja"):
            print(f'{v["ShortName"]:30} {v["Gender"]}')

asyncio.run(list_voices())
```

## The Async Problem

### edge-tts Is Async-Only

edge-tts is built on `aiohttp` and exposes an exclusively asynchronous API. The `Communicate` class uses `async for` to stream audio chunks over a WebSocket connection, and its `save()` method is a coroutine:

```python
communicate = edge_tts.Communicate(text, voice)
await communicate.save(filepath)  # This is a coroutine
```

Our pipeline, however, is synchronous. `main.py` calls each module's function in sequence, and none of the other modules use async. We need a bridge.

### `asyncio.run()` as the Bridge

The standard approach is to wrap the async call in `asyncio.run()`, which creates an event loop, runs the coroutine to completion, and tears down the loop:

```python
def generate_audio(text: str, filename: str) -> str:
    os.makedirs(config.AUDIO_DIR, exist_ok=True)
    filepath = os.path.join(config.AUDIO_DIR, filename)
    asyncio.run(_generate(text, filepath))
    return filepath
```

This is the simplest async-to-sync bridge available. `asyncio.run()` was added in Python 3.7 specifically for this use case — running a single async entry point from synchronous code. It handles event loop creation, execution, and cleanup in one call.

The pipeline calls `generate_audio()` twice (once for the word, once for the sentence), which means `asyncio.run()` creates and destroys the event loop twice. This is slightly inefficient — reusing a single event loop would avoid the setup/teardown overhead — but the overhead is negligible compared to the network round-trip for TTS synthesis. Simplicity wins.

### The Windows Event Loop Fix

```python
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

This line addresses a specific issue on Windows with Python 3.8. The default event loop on Windows is `ProactorEventLoop`, which is based on Windows I/O Completion Ports. When `asyncio.run()` closes a `ProactorEventLoop`, any still-pending transport objects (from `aiohttp`'s connection pool) raise a `RuntimeError: Event loop is closed` during garbage collection.

The error is cosmetic — it does not affect the generated audio or the program's exit code — but it produces alarming stack traces. Switching to `SelectorEventLoop` via the policy avoids the issue entirely. `SelectorEventLoop` uses the `select()` system call instead of IOCP and does not have the same cleanup problem.

This policy is set at module import time, before any event loop is created. It affects all subsequent `asyncio.run()` calls in the process. Since the TTS module is the only async code in the project, this has no side effects.

On Python 3.10+, this issue was fixed in the standard library and the policy override is unnecessary but harmless. The `sys.platform` check ensures it is only applied on Windows regardless of version.

## Implementation

The full module:

```python
import asyncio
import os
import sys
import edge_tts
import config

VOICE = "ja-JP-NanamiNeural"

# Fix asyncio ProactorEventLoop RuntimeError on Windows Python 3.8
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _generate(text: str, filepath: str) -> None:
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(filepath)


def generate_audio(text: str, filename: str) -> str:
    """Generate a Japanese TTS audio file and return its path."""
    os.makedirs(config.AUDIO_DIR, exist_ok=True)
    filepath = os.path.join(config.AUDIO_DIR, filename)
    asyncio.run(_generate(text, filepath))
    return filepath
```

### The Private Async Function

```python
async def _generate(text: str, filepath: str) -> None:
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(filepath)
```

The underscore prefix signals that `_generate` is not part of the module's public interface. External code calls `generate_audio()`; the async internals are an implementation detail.

`edge_tts.Communicate` takes the text to synthesize and the voice ID. The `save()` method opens a WebSocket connection to Microsoft's TTS service, streams audio chunks as they are generated, and writes the concatenated result to the specified file path. The output format is MP3 by default.

### The Public Function

```python
def generate_audio(text: str, filename: str) -> str:
    """Generate a Japanese TTS audio file and return its path."""
    os.makedirs(config.AUDIO_DIR, exist_ok=True)
    filepath = os.path.join(config.AUDIO_DIR, filename)
    asyncio.run(_generate(text, filepath))
    return filepath
```

The function takes a text string and a filename, not a full path. The filename is combined with `config.AUDIO_DIR` to produce the full path. This separation matters because downstream consumers need both pieces of information for different purposes:

- The **file path** (`audio/食べる_word.mp3`) is needed to read the file from disk when uploading to Anki via AnkiConnect
- The **filename** (`食べる_word.mp3`) is needed for the Anki `[sound:]` tag, which references files by name only (Anki stores all media in a flat directory)

By accepting the filename as a parameter and returning the full path, the function lets the caller hold onto both values. This is how `main.py` constructs the `audio_paths` dict:

```python
audio_paths = {
    "word_path": word_audio_path,           # Full path for file I/O
    "word_filename": word_filename,          # Bare filename for Anki tags
    "sentence_path": sentence_audio_path,
    "sentence_filename": sentence_filename,
}
```

### Directory Creation

```python
os.makedirs(config.AUDIO_DIR, exist_ok=True)
```

The `audio/` directory is created on every call if it does not already exist. The `exist_ok=True` flag makes this idempotent — it is a no-op if the directory is already there. This is called twice per pipeline run (once per audio file), which is redundant but harmless. The alternative — checking once in `main.py` — would leak the TTS module's implementation detail (where it writes files) into the orchestrator.

## Filename Normalization

### The Problem

Filenames are constructed from Japanese text. The input word 食べる needs to become a valid filename on Windows, macOS, and Linux. These operating systems have different rules about which characters are allowed in filenames, and Anki's media system adds its own constraints.

Problematic characters include:

- Path separators (`/`, `\`) — interpreted as directory boundaries
- Special characters (`?`, `*`, `<`, `>`, `|`, `:`, `"`) — forbidden on Windows
- Newlines and control characters — generally forbidden everywhere
- Extremely long filenames — most filesystems cap at 255 bytes

Japanese characters (kanji, hiragana, katakana) are valid in filenames on all modern operating systems. The risk comes from edge cases: words containing punctuation marks (like the interpunct `・` used in katakana compounds), or LLM-generated sentences containing quotation marks or other special characters.

### The Sanitization Function

Filename sanitization is handled in `main.py` rather than in the TTS module:

```python
def sanitize_filename(text: str) -> str:
    """Create a safe filename from Japanese text."""
    return re.sub(r'[^\w\s-]', '', text, flags=re.UNICODE).strip()[:50]
```

This function:

1. **Strips non-word characters** — `\w` with the `re.UNICODE` flag matches letters, digits, and underscores in any script (including CJK characters). The pattern `[^\w\s-]` removes everything that is not a word character, whitespace, or hyphen. This eliminates punctuation, path separators, and special characters while preserving Japanese text.

2. **Truncates to 50 characters** — Prevents excessively long filenames from sentences. Fifty characters is well under any filesystem limit and produces readable filenames.

The function lives in `main.py` rather than `tts.py` because filename construction is an orchestration concern. The TTS module accepts a pre-sanitized filename and writes to it; it does not know or decide how filenames are derived from input data.

### The Naming Convention

`main.py` applies the sanitization and appends a suffix to distinguish between the two audio files:

```python
safe_word = sanitize_filename(word)
word_filename = f"{safe_word}_word.mp3"
sentence_filename = f"{safe_word}_sentence.mp3"
```

For the input 食べる, this produces:

- `食べる_word.mp3` — audio of the word spoken in isolation
- `食べる_sentence.mp3` — audio of the full example sentence

The `_word` and `_sentence` suffixes ensure the two files have distinct names. Without them, both files would be named `食べる.mp3` and the second write would overwrite the first.

## How Anki Handles Media Files

Understanding how Anki stores and references media is necessary to get the file path plumbing right.

### Anki's Media Folder

Anki stores all media files (audio, images, video) in a single flat directory per profile. On a typical installation:

- **Windows**: `%APPDATA%\Anki2\<profile>\collection.media\`
- **macOS**: `~/Library/Application Support/Anki2/<profile>/collection.media/`
- **Linux**: `~/.local/share/Anki2/<profile>/collection.media/`

There are no subdirectories. All media files for all decks live in the same folder. Files are referenced by name only — Anki does not use paths.

### The `[sound:]` Tag

In card templates and field content, audio is referenced with the tag:

```
[sound:食べる_word.mp3]
```

When Anki renders a card, it looks for a file with that exact name in the media folder. If the file exists, it renders a play button (or auto-plays, depending on settings). If the file does not exist, the tag is rendered as plain text.

This is why the `audio_paths` dict tracks filenames separately from full paths. The flashcard module uses the filename to construct the `[sound:]` tag. The AnkiConnect module uses the full path to read the file from disk and upload it to Anki's media folder.

### The Two-Step Delivery

Audio files reach Anki through a two-step process:

1. **TTS module** writes `.mp3` files to the local `audio/` directory
2. **AnkiConnect module** reads those files, base64-encodes them, and sends them to Anki via the `storeMediaFile` API action

The local `audio/` directory is a staging area. After the AnkiConnect module uploads the files, the copies in `audio/` are no longer needed (Anki has its own copy in the media folder). They are not automatically deleted — they serve as a cache and a debugging aid. If something goes wrong with the Anki upload, you can inspect the generated audio files directly.

## What Gets Generated

### Word Audio

The vocabulary word is spoken in isolation. For 食べる, the TTS service receives the string `食べる` and produces natural Japanese pronunciation: たべる with appropriate pitch accent.

Japanese TTS handles kanji-to-speech conversion internally — the service has its own reading disambiguation. For common words, this is reliable. For rare words or words with multiple readings, the TTS service may choose a different reading than intended. This is generally not a problem for vocabulary study, where the correct reading is displayed on the flashcard alongside the audio.

### Sentence Audio

The LLM-generated example sentence is spoken as a complete utterance. For a sentence like 彼は毎日ご飯を食べます, the TTS service produces natural sentence-level prosody — appropriate pauses between phrases, rising and falling intonation, and connected speech patterns that differ from reading each word individually.

Sentence-level audio is pedagogically valuable because it demonstrates how the word sounds in context: where it falls in the rhythm of a natural sentence, how it connects to surrounding particles and verb endings, and how sentence-level pitch patterns interact with word-level pitch accent.

## Role in the Pipeline

The TTS module is a pure producer — it creates files and returns their paths. It does not read from or depend on the retrieval module's output directly. Its inputs come from `main.py`, which passes the raw word string and the LLM's generated sentence.

The module's output — file paths — is consumed by two downstream modules:

- **`flashcard.py`** reads the filenames to construct `[sound:]` tags in the card's HTML
- **`anki_connect.py`** reads the full file paths to upload the audio data to Anki

This is the point in the pipeline where the data representation shifts. The retrieval and LLM modules deal in text — strings, dicts, JSON. The TTS module introduces files into the data flow. From here forward, the pipeline carries both structured text data and references to binary files on disk, and the downstream modules must handle both.
