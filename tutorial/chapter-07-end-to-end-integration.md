# Chapter 7: End-to-End Integration

This chapter covers `main.py`: the orchestrator that wires all five modules into a single CLI command. The previous chapters examined each module in isolation: what it does, what it expects, and what it produces. This chapter is about what happens when they run together. The focus is on the pipeline's execution flow, how data moves between stages, how errors are handled across service boundaries, latency characteristics, and the construction of the final payload that reaches Anki.

## The Orchestrator's Role

`main.py` has exactly one job: call the five modules in sequence, pass data between them, and report progress. It does not contain business logic. It does not transform data beyond filename sanitization. It does not make decisions about flashcard content. Every meaningful operation happens inside a module.

This is a deliberate architectural constraint. The orchestrator is the one place in the codebase that knows about all five modules simultaneously, which makes it the easiest place to accidentally accumulate logic that should live elsewhere. Keeping it thin means that each module remains independently testable and replaceable, as discussed in Chapter 1.

## Implementation

```python
import argparse
import re
import sys

from modules.retriever import lookup
from modules.llm import generate_examples
from modules.tts import generate_audio
from modules.flashcard import build_flashcard
from modules.anki_connect import add_note


def sanitize_filename(text: str) -> str:
    """Create a safe filename from Japanese text."""
    return re.sub(r'[^\w\s-]', '', text, flags=re.UNICODE).strip()[:50]


def main():
    parser = argparse.ArgumentParser(description="Generate an Anki flashcard for a Japanese word")
    parser.add_argument("word", help="Japanese word to create a flashcard for")
    args = parser.parse_args()
    word = args.word

    # Step 1: Dictionary lookup
    print(f"[1/5] Looking up '{word}'...")
    try:
        vocab_info = lookup(word)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"      Readings: {', '.join(vocab_info['readings'])}")
    print(f"      Meanings: {', '.join(vocab_info['meanings'])}")

    # Step 2: LLM examples
    print(f"[2/5] Generating example sentence...")
    try:
        llm_output = generate_examples(vocab_info)
    except ConnectionError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"      Example: {llm_output['example_sentence']}")
    print(f"      Translation: {llm_output['example_sentence_translation']}")

    # Step 3: TTS audio
    print(f"[3/5] Generating audio...")
    safe_word = sanitize_filename(word)
    word_filename = f"{safe_word}_word.mp3"
    sentence_filename = f"{safe_word}_sentence.mp3"

    word_audio_path = generate_audio(word, word_filename)
    sentence_audio_path = generate_audio(llm_output["example_sentence"], sentence_filename)
    print(f"      Audio saved to {word_audio_path} and {sentence_audio_path}")

    audio_paths = {
        "word_path": word_audio_path,
        "word_filename": word_filename,
        "sentence_path": sentence_audio_path,
        "sentence_filename": sentence_filename,
    }

    # Step 4: Build flashcard
    print(f"[4/5] Building flashcard...")
    flashcard = build_flashcard(vocab_info, llm_output, audio_paths)
    print(f"      Front: {flashcard['front']}")

    # Step 5: Add to Anki
    print(f"[5/5] Adding to Anki...")
    try:
        note_id = add_note(flashcard)
    except ConnectionError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"\nFlashcard added successfully! (Note ID: {note_id})")


if __name__ == "__main__":
    main()
```

## CLI Interface

```python
parser = argparse.ArgumentParser(description="Generate an Anki flashcard for a Japanese word")
parser.add_argument("word", help="Japanese word to create a flashcard for")
args = parser.parse_args()
word = args.word
```

The tool takes a single positional argument: the Japanese word. `argparse` handles `--help` output, missing argument errors, and argument parsing. Usage:

```
python main.py 食べる
python main.py 輪廻
python main.py おはよう
```

There are no flags, no options, and no subcommands. One word in, one flashcard out. This minimalism is intentional, the tool does one thing and the configuration lives in `config.py`, not in CLI arguments. If you want to change the deck name, voice, or model, you edit the config file. CLI arguments are for things that change on every invocation; configuration is for things that change rarely.

### Encoding on Windows

The word argument passes through the operating system's command-line encoding. On modern Windows systems with Python 3, UTF-8 is handled correctly and Japanese characters can be passed directly. However, the output encoding is a separate issue, Windows console output uses the system's active code page (often CP932 for Japanese locale, or CP437 for Western locale), which may not be able to display all characters. This is why the pipeline's console output can show garbled characters like `�H�ׂ�` even when the underlying data is correct.

The garbled display is cosmetic. The strings stored in Python, sent to LM Studio, passed to edge-tts, and written to Anki are all correct UTF-8. Only the `print()` calls to the console are affected, and only on Windows systems where the console code page does not support the characters being printed.

## Pipeline Execution Flow

The five steps execute strictly in sequence. Each step depends on the output of the previous step, making parallelization impossible without restructuring the data dependencies.

### Step 1: Dictionary Lookup

```python
print(f"[1/5] Looking up '{word}'...")
try:
    vocab_info = lookup(word)
except ValueError as e:
    print(f"Error: {e}")
    sys.exit(1)
print(f"      Readings: {', '.join(vocab_info['readings'])}")
print(f"      Meanings: {', '.join(vocab_info['meanings'])}")
```

The first step queries the local dictionary database. This is the fastest operation in the pipeline, a SQLite lookup that completes in single-digit milliseconds. It is also the gate: if the word is not in the dictionary, nothing else runs.

`vocab_info` is the first data artifact. It flows forward to steps 2 and 4.

### Step 2: LLM Generation

```python
print(f"[2/5] Generating example sentence...")
try:
    llm_output = generate_examples(vocab_info)
except ConnectionError as e:
    print(f"Error: {e}")
    sys.exit(1)
print(f"      Example: {llm_output['example_sentence']}")
print(f"      Translation: {llm_output['example_sentence_translation']}")
```

The second step sends `vocab_info` to the local LLM and receives generated content. This is typically the slowest operation in the pipeline, inference time depends on hardware, model size, and quantization level, but 2–10 seconds on a GPU is typical.

`llm_output` is the second data artifact. It flows forward to steps 3 and 4. Step 3 needs the example sentence text for audio synthesis. Step 4 needs all three generated fields for the flashcard.

### Step 3: Audio Generation

```python
print(f"[3/5] Generating audio...")
safe_word = sanitize_filename(word)
word_filename = f"{safe_word}_word.mp3"
sentence_filename = f"{safe_word}_sentence.mp3"

word_audio_path = generate_audio(word, word_filename)
sentence_audio_path = generate_audio(llm_output["example_sentence"], sentence_filename)
print(f"      Audio saved to {word_audio_path} and {sentence_audio_path}")

audio_paths = {
    "word_path": word_audio_path,
    "word_filename": word_filename,
    "sentence_path": sentence_audio_path,
    "sentence_filename": sentence_filename,
}
```

The third step is the only one where the orchestrator does meaningful data preparation beyond passing dicts between modules. It:

1. Sanitizes the word into a filesystem-safe string (covered in Chapter 5)
2. Constructs filenames with `_word` and `_sentence` suffixes
3. Calls `generate_audio()` twice, once for the word, once for the sentence
4. Assembles the `audio_paths` dict that downstream modules need

This preparation lives in `main.py` rather than in the TTS module because it bridges information from multiple sources. The word comes from the CLI argument, the sentence comes from the LLM output, and the filename convention is an orchestration-level decision about how to name things. No single module has all of this context.

The two `generate_audio()` calls are independent, the sentence audio does not depend on the word audio. In principle, they could run in parallel. In practice, `asyncio.run()` creates and destroys an event loop per call (as discussed in Chapter 5), and the TTS service processes requests fast enough that the sequential overhead is negligible compared to the LLM step.

### Step 4: Flashcard Assembly

```python
print(f"[4/5] Building flashcard...")
flashcard = build_flashcard(vocab_info, llm_output, audio_paths)
print(f"      Front: {flashcard['front']}")
```

The fourth step is the convergence point. `build_flashcard` receives data from steps 1, 2, and 3 and produces a single dict containing the finished card. This is a pure in-memory transformation with no I/O, it completes in microseconds.

No error handling is needed here. `build_flashcard` operates on dicts that have already been validated by the modules that produced them. If `vocab_info` has an unexpected shape, that is a bug in `retriever.py`, not a runtime error to catch in `main.py`.

### Step 5: Anki Delivery

```python
print(f"[5/5] Adding to Anki...")
try:
    note_id = add_note(flashcard)
except ConnectionError as e:
    print(f"Error: {e}")
    sys.exit(1)
except RuntimeError as e:
    print(f"Error: {e}")
    sys.exit(1)

print(f"\nFlashcard added successfully! (Note ID: {note_id})")
```

The final step delivers the flashcard and its media files to Anki. Two exception types are caught:

- `ConnectionError`: Anki is not running or AnkiConnect is not installed. The most common failure mode.
- `RuntimeError`: AnkiConnect returned an application-level error. The most common case is a duplicate note.

If both succeed, the note ID is printed as confirmation. The note ID is Anki's internal identifier for the created note, it can be used with AnkiConnect's other actions (`updateNoteFields`, `deleteNotes`, etc.) if you want to programmatically modify the card later.

## Data Flow Summary


Three independent data streams (`vocab_info`, `llm_output`, `audio_paths`) converge at step 4 and are consumed as a single payload in step 5. The orchestrator holds all three in local variables until they are needed.

## Error Handling Across Service Boundaries

The pipeline interacts with three external services, each with its own failure mode:

| Service | How It Fails | Exception Type | Caught In |
|---------|-------------|----------------|-----------|
| jamdict (SQLite) | Word not found | `ValueError` | Step 1 |
| LM Studio (HTTP) | Server not running | `ConnectionError` | Step 2 |
| LM Studio (HTTP) | Malformed JSON response | `json.JSONDecodeError` | Uncaught |
| edge-tts (WebSocket) | Network failure | Various | Uncaught |
| AnkiConnect (HTTP) | Anki not running | `ConnectionError` | Step 5 |
| AnkiConnect (HTTP) | Duplicate note, bad note type | `RuntimeError` | Step 5 |

### What Is Caught and Why

The caught exceptions share a property: they represent **expected, actionable failures**. The user can fix them (start LM Studio, open Anki, spell the word correctly) and re-run the command. The error messages are written to tell the user what to do, not what went wrong internally.

### What Is Not Caught and Why

`json.JSONDecodeError` (malformed LLM output) and edge-tts network errors are not caught. These represent **unexpected failures**, they indicate a problem that the user cannot fix by restarting a service. A model that produces unparseable output needs a different model or a different prompt. A network failure during TTS means the internet connection is down. In both cases, the Python traceback provides more diagnostic information than a friendly error message would.

This is a conscious trade-off. A production web service would catch everything and return structured errors. A CLI tool used by its developer benefits from unfiltered tracebacks when unexpected things go wrong.

### Fail-Fast Behavior

Every caught exception results in `sys.exit(1)`, immediate termination with a nonzero exit code. No step attempts to recover from a previous step's failure. If the dictionary lookup fails, the tool does not try an alternative spelling. If LM Studio is down, the tool does not skip to TTS with a placeholder sentence.

This is appropriate because partial output has no value in this pipeline. A flashcard without a definition is useless. A flashcard without audio is incomplete. A flashcard that was generated but not inserted into Anki accomplished nothing. The pipeline produces a complete flashcard or it produces nothing.

The nonzero exit code (`sys.exit(1)`) is a Unix convention that allows shell scripts to detect failure. If you were to wrap this tool in a batch processing script, you could check the exit code to decide whether to continue:

```bash
for word in 食べる 飲む 走る; do
    python main.py "$word" || echo "Failed: $word"
done
```

## Latency Profile

The five steps have dramatically different execution times:

| Step | Operation | Typical Latency | Bottleneck |
|------|-----------|----------------|------------|
| 1. Retriever | SQLite query | <10 ms | Disk I/O (first call only) |
| 2. LLM | Local inference | 2–10 s | GPU compute |
| 3. TTS (word) | edge-tts synthesis | 0.5–2 s | Network round-trip |
| 3. TTS (sentence) | edge-tts synthesis | 0.5–2 s | Network round-trip |
| 4. Flashcard | String concatenation | <1 ms | None |
| 5. AnkiConnect | 4 HTTP requests to localhost | <50 ms | None |

**Total wall time: ~3–15 seconds**, dominated by LLM inference.

The LLM step is the clear bottleneck. Everything else combined takes under 5 seconds even in the worst case. If you want to make the tool faster, the highest-impact change is using a smaller or more aggressively quantized model, or using a GPU with higher memory bandwidth.

The two TTS calls are the second-largest contributor. They could be parallelized with each other (they are independent), and they could also overlap with LLM inference if the pipeline were restructured, you could start generating word audio as soon as step 1 completes, since the word audio does not depend on the LLM output. However, this kind of concurrent restructuring adds significant complexity (async orchestration, error propagation across concurrent tasks) for a savings of 1–4 seconds. For an interactive single-word tool, sequential execution is the right trade-off.

## The Progress Interface

```python
print(f"[1/5] Looking up '{word}'...")
print(f"      Readings: {', '.join(vocab_info['readings'])}")
```

Each step prints a bracketed step counter (`[1/5]`), a description of what is happening, and then the intermediate results. This serves two purposes:

**1. Progress indication.** The LLM step takes several seconds. Without output, the user would see a frozen terminal and wonder if the tool is working. The step counter sets expectations, the user knows there are five steps and can see which one is currently running.

**2. Transparency.** Printing intermediate results (readings, meanings, generated sentence, audio paths) lets the user inspect the pipeline's work at each stage. If the LLM generates an odd sentence, the user sees it immediately rather than having to inspect the finished flashcard in Anki. This is valuable during development and for building trust in the tool's output.

The output for a successful run looks like:

```
[1/5] Looking up '食べる'...
      Readings: たべる
      Meanings: to eat, to live on (e.g. a salary), to live off, to subsist on
[2/5] Generating example sentence...
      Example: 彼は毎日ご飯を食べます。
      Translation: He eats rice every day.
[3/5] Generating audio...
      Audio saved to audio/食べる_word.mp3 and audio/食べる_sentence.mp3
[4/5] Building flashcard...
      Front: 食べる (たべる) [sound:食べる_word.mp3]
[5/5] Adding to Anki...

Flashcard added successfully! (Note ID: 1769778487044)
```

## Revisiting the Architecture

With all seven chapters complete, it is worth stepping back to see the full system as a single unit.

The project implements a five-stage linear pipeline that combines deterministic retrieval with probabilistic generation. The retrieval layer (Chapter 3) provides the factual foundation, verified dictionary data that the learner can trust. The generative layer (Chapter 4) provides contextual enrichment, example sentences that make vocabulary items memorable. The media layer (Chapter 5) provides audio, pronunciation models that support listening and speaking practice. The assembly and delivery layers (Chapter 6) format everything for Anki's consumption and push it into the learner's review queue.

Each layer is implemented as a Python module with a single public function. The modules do not import each other. The orchestrator (`main.py`) is the only file that knows about all of them, and it does nothing beyond calling them in order and passing data between them.

The system runs almost entirely locally. The dictionary is a SQLite database on disk. The LLM runs on your GPU through LM Studio. The flashcards are delivered to a local Anki instance. The one external dependency, Microsoft's TTS service, is a pragmatic compromise that sends minimal data and could be replaced with a local alternative.

This architecture is not novel. It is a straightforward application of well-understood patterns: pipelines for sequential data processing, hybrid systems for combining deterministic and probabilistic components, and local-first design for privacy and control. The value is not in any individual pattern but in how they compose into a tool that is simple to understand, simple to modify, and genuinely useful for daily language study.
