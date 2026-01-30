# Chapter 1: Introduction and Architectural Overview

## This tutorial

This tutorial walks through building a command-line tool that generates Japanese-language flashcards and inserts them directly into Anki. Given a single Japanese word as input, the system:

1. Looks up the word in a local Japanese dictionary database.
2. Sends the structured dictionary data to a locally-hosted language model to generate example sentences.
3. Synthesizes Japanese audio for the word and sentence.
4. Formats everything into a flashcard.
5. Pushes the flashcard into Anki via its local API.

The end result is a pipeline that turns a Japanese word into a complete, audio-equipped Anki flashcard in a single command:

```
python main.py 食べる
```

This tool combines deterministic data retrieval with probabilistic AI generation, runs entirely on local infrastructure, and manages multiple independent services through a linear pipeline.

## Who This Tutorial Is For

This tutorial assumes you are comfortable writing Python (standard library usage, pip, dicts, type hints), familiar with REST APIs at a practical level (HTTP methods, JSON payloads, calling localhost services), and have a conceptual understanding of what large language models do, though not how to train or fine-tune them. Basic comfort with command-line tools is expected.

## Hybrid AI: Deterministic Ground Truth and Probabilistic Generation

The term "hybrid AI" gets used loosely, but here it refers to a system where some components produce deterministic, verifiable outputs and others produce probabilistic, generated outputs, and the two are composed together deliberately.

### The Deterministic Layer

The first stage of the pipeline queries **[JMdict](https://www.edrdg.org/jmdict/j_jmdict.html)** and **[KANJIDIC2](https://www.edrdg.org/wiki/index.php/KANJIDIC_Project)**, two established, community-maintained Japanese dictionary databases managed by the [Electronic Dictionary Research and Development Group (EDRDG)](https://www.edrdg.org/), through the `jamdict` library. This is a conventional database lookup. Given the input `食べる`, it returns:

- **Readings**: たべる
- **Meanings**: to eat, to live on (e.g. a salary), to live off, to subsist on
- **Kanji data**: component radicals, stroke counts, readings for each character

This data is ground truth. It comes from a curated, peer-reviewed lexicographic database that has been maintained since 1991. The readings and definitions are not generated, predicted, or approximated, and instead are facts about the Japanese language, stored and retrieved without transformation.

This distinction matters because language learning flashcards have a low tolerance for error. If a flashcard tells you that 食べる means "to drink," you will learn the wrong thing and practice it through spaced repetition, compounding the mistake over time. Dictionary data anchors the flashcard in verified information.

### The Probabilistic Layer

The second stage sends the dictionary data to a large language model running locally via LM Studio. The model receives the word, its readings, and its meanings, and generates:

- A natural Japanese example sentence using the word
- An English translation of that sentence
- A concise English gloss for the vocabulary item

This is generative output. The model produces plausible, contextually appropriate content, but there is no guarantee that any particular sentence is grammatically perfect or that the translation is precisely correct. The output is probabilistic; run the same query twice and you may get different sentences.

### Why This Composition Matters

The architecture is structured so that the deterministic layer provides the data the learner depends on for correctness (readings, meanings, kanji decomposition), while the probabilistic layer provides data that enhances the learning experience (example sentences, contextual usage). The generated content is always presented alongside the verified content.

## Why Local-Only

Every component in this system runs on your own machine. There are no API calls to cloud services, no data leaves your network, and no usage is metered or rate-limited.

### What Runs Where

| Component | Runs On | Network? |
|-----------|---------|----------|
| jamdict (dictionary lookup) | Local SQLite database | None |
| LM Studio (LLM inference) | Local GPU/CPU | None (localhost only) |
| edge-tts (audio synthesis) | Microsoft Edge TTS service | Outbound HTTPS* |
| AnkiConnect (flashcard insertion) | Local Anki instance | None (localhost only) |

*\*edge-tts is an exception; it calls Microsoft's TTS endpoint; local TTS options for Japanese exist but produce noticeably lower quality audio and requires more setup with large chances of failure. The text sent to the TTS service is a single Japanese word or sentence, which is minimal in terms of data exposure. Local TTS alternatives are discussed in Chapter 5.*

### Privacy

Language learning vocabulary reveals information about a person's interests, proficiency level, travel plans or cultural engagement. A cloud-based flashcard generation service or other services would accumulate a profile of each user's learning trajectory or interests. Running locally means this data stays on your own system.

### Latency and Availability

Cloud API calls introduce network latency and depend on external service availability. Local inference through LM Studio has higher per-request latency (depending on your hardware), but it has zero network overhead and is available whenever your machine is on. There are no rate limits, API quotas or degraded service windows.

### Cost

Cloud LLM APIs charge per token. If you're generating flashcards for hundreds of vocabulary items, then the costs will add up. Local inference has a one-time hardware cost (a capable GPU) and a marginal cost per request. For a tool intended to be used daily as part of a language learning routine, local inference is favorable.

### Control

Running your own model means you can swap it out. If a new model handles Japanese better, you load it into LM Studio and the rest of the pipeline is unchanged. You are not locked into a provider's model selection, pricing, or deprecation schedule.

## System Architecture

The system is structured as a linear pipeline; each stage takes input from the previous stage and produces output for the next. 

### Pipeline Stages

Each module is a Python file in the `modules/` directory with a single public function:

| Module | Function | Input | Output |
|--------|----------|-------|--------|
| `retriever.py` | `lookup(word)` | Japanese string | Dict of readings, meanings, kanji info |
| `llm.py` | `generate_examples(vocab_info)` | Dict from retriever | Dict with example sentence, translation, gloss |
| `tts.py` | `generate_audio(text, filename)` | Text + filename | File path to generated .mp3 |
| `flashcard.py` | `build_flashcard(vocab_info, llm_output, audio_paths)` | Dicts from prior stages | Dict with front/back HTML fields |
| `anki_connect.py` | `add_note(flashcard)` | Dict from flashcard module | Integer note ID |

### Data Flow

The data flowing through the pipeline accumulates rather than transforms. The retriever produces dictionary data; the LLM module adds generated content to it; the TTS module adds audio file paths; the flashcard module combines everything into a presentation format; and the AnkiConnect module delivers the result.

### Module Boundaries

Each module depends on at most the Python standard library, its own specific third-party package, and the shared `config.py` file. Some modules use all three; `flashcard.py` uses none of them, it is pure data transformation with zero imports. No module imports another module. The orchestration happens entirely in `main.py`, which imports all five modules and calls them in sequence.

This means any module can be tested, replaced, or modified in isolation. If you wanted to swap `jamdict` for a different dictionary backend, you would rewrite `retriever.py` to return the same dict shape and nothing else would change. If you want to use a cloud LLM instead of LM Studio, you would rewrite `llm.py`.

### Error Handling Strategy

Errors in this pipeline are fail-fast. If the dictionary lookup finds no results, the program exits immediately with a message. If LM Studio is not running, the program exits. If AnkiConnect is not reachable, the program exits. There is no retry logic, no fallback behavior, and no partial output.

This is appropriate for a CLI tool run interactively by a human. The user can read the error message, fix the problem (start LM Studio, open Anki, correct the input word), and re-run the command. Adding retry logic or graceful degradation would add complexity without meaningfully improving the user experience for a single-word-at-a-time workflow.

### Configuration

All external endpoints, model names, deck names, and file paths are defined in `config.py` as module-level constants:

```python
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_STUDIO_MODEL = "local-model"
ANKI_CONNECT_URL = "http://localhost:8765"
ANKI_DECK_NAME = "Japanese"
ANKI_NOTE_TYPE = "Basic"
AUDIO_DIR = "audio/"
```

These are not read from environment variables or a config file. For a single-user local tool, plain constants in a Python file are the simplest configuration mechanism — they are easy to read, easy to change, and require no parsing logic.

## What This Tutorial Does Not Cover

This tutorial focuses on one specific system. The following topics are outside its scope:

- Fine-tuning or training language models
- Anki card template design or custom CSS styling
- Production deployment (web services, containerization, CI/CD)
- Automated testing or test frameworks
- Cloud API integration (OpenAI, Anthropic, etc.)
- Mobile Anki clients or AnkiWeb sync

## Structure

The remaining chapters move from environment setup through each layer of the pipeline, building up to the fully integrated system.

- **Chapter 2: Environment Setup** — Configuring the Python environment, installing dependencies, setting up LM Studio, Anki with AnkiConnect, and all other tooling required to develop and run the project.
- **Chapter 3: Retrieval** — Implementing the dictionary lookup module. Covers the JMdict and KANJIDIC2 data sources, the `jamdict` library, and the query logic for retrieving exact definitions, readings, and kanji metadata. This retrieved data forms the deterministic ground truth that anchors the generative stages.
- **Chapter 4: Generative Logic** — Running LLMs locally for structured text generation. Covers model selection and quantization trade-offs, inference server setup with LM Studio, prompt engineering for consistent JSON output, and fallback strategies.
- **Chapter 5: Local Media Generation** — Implementing text-to-speech audio synthesis with edge-tts. Covers async audio generation, normalization standards, and handling of file paths for media linkage in Anki.
- **Chapter 6: Flashcard Construction and Anki Injection** — Assembling the outputs from prior stages into Anki-compatible flashcard fields, and delivering them via the AnkiConnect protocol including media file storage.
- **Chapter 7: End-to-End Integration** — The final technical chapter. Covers orchestration of all components into a single CLI pipeline, error handling across service boundaries, latency considerations, and construction of the final payload for injection into Anki.
- **Chapter 8: Conclusion and Future Work** — Summary of the implemented architecture, local vs. cloud trade-offs, and suggestions for technical extensions.
