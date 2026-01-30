# Chapter 1: Introduction and Architectural Overview

## What We're Building

This tutorial walks through building a command-line tool that generates Japanese-language flashcards and inserts them directly into Anki. Given a single Japanese word as input, the system:

1. Looks up the word in a local Japanese dictionary database
2. Sends the structured dictionary data to a locally-hosted language model to generate example sentences
3. Synthesizes Japanese audio for the word and sentence
4. Formats everything into a flashcard
5. Pushes the flashcard into Anki via its local API

The end result is a five-stage pipeline that turns a Japanese word into a complete, audio-equipped Anki flashcard in a single command:

```
python main.py 食べる
```

The tool is interesting not because of what it produces — you could make flashcards by hand — but because of *how* it produces them. The architecture combines deterministic data retrieval with probabilistic AI generation, runs entirely on local infrastructure, and coordinates multiple independent services through a linear pipeline. These are patterns worth understanding in detail.

## Hybrid AI: Deterministic Ground Truth Meets Probabilistic Generation

The term "hybrid AI" gets used loosely, but here it refers to something specific: a system where some components produce *deterministic, verifiable outputs* and others produce *probabilistic, generated outputs*, and the two are composed together deliberately.

### The Deterministic Layer

The first stage of the pipeline queries **JMdict** and **KANJIDIC2** — two established, community-maintained Japanese dictionary databases — through the `jamdict` library. This is a conventional database lookup. Given the input `食べる`, it returns:

- **Readings**: たべる
- **Meanings**: to eat, to live on (e.g. a salary), to live off, to subsist on
- **Kanji data**: component radicals, stroke counts, readings for each character

This data is *ground truth*. It comes from a curated, peer-reviewed lexicographic database that has been maintained since 1991. The readings and definitions are not generated, predicted, or approximated — they are facts about the Japanese language, stored and retrieved without transformation.

This distinction matters because language learning flashcards have a low tolerance for error. If a flashcard tells you that 食べる means "to drink," you will learn the wrong thing and practice it through spaced repetition, compounding the mistake over time. Dictionary data anchors the flashcard in verified information.

### The Probabilistic Layer

The second stage sends the dictionary data to a large language model running locally via LM Studio. The model receives the word, its readings, and its meanings, and generates:

- A natural Japanese example sentence using the word
- An English translation of that sentence
- A concise English gloss for the vocabulary item

This is *generative* output. The model produces plausible, contextually appropriate content, but there is no guarantee that any particular sentence is grammatically perfect or that the translation is precisely correct. The output is probabilistic — run the same query twice and you may get different sentences.

This is an acceptable trade-off because example sentences serve a different pedagogical function than definitions. A definition must be correct. An example sentence must be *useful* — it should demonstrate the word in a natural context and be at an appropriate difficulty level. Minor imperfections in a generated sentence are less damaging than a wrong definition, and the alternative (manually writing example sentences for every vocabulary item) does not scale.

### Why This Composition Matters

The architecture is deliberately structured so that the deterministic layer provides the data the learner *depends on for correctness* (readings, meanings, kanji decomposition), while the probabilistic layer provides data that *enhances the learning experience* (example sentences, contextual usage). The generated content is always presented alongside the verified content, so the learner has a reliable reference point.

This is a general pattern worth recognizing: **use AI generation where the cost of imperfection is low and the cost of manual effort is high, and use deterministic systems where correctness is non-negotiable.** Many practical AI applications follow this structure — retrieval-augmented generation (RAG) is a well-known instance of it, where a retrieval system provides factual grounding and a language model provides fluent synthesis.

## Why Local-Only

Every component in this system runs on your own machine. There are no API calls to cloud services, no data leaves your network, and no usage is metered or rate-limited. This is a deliberate architectural choice with specific trade-offs.

### What Runs Where

| Component | Runs On | Network? |
|-----------|---------|----------|
| jamdict (dictionary lookup) | Local SQLite database | None |
| LM Studio (LLM inference) | Local GPU/CPU | None (localhost only) |
| edge-tts (audio synthesis) | Microsoft Edge TTS service | Outbound HTTPS* |
| AnkiConnect (flashcard insertion) | Local Anki instance | None (localhost only) |

*\*edge-tts is the one exception — it calls Microsoft's TTS endpoint. This is a pragmatic compromise: local TTS options for Japanese exist but produce noticeably lower quality audio. The text sent to the TTS service is a single Japanese word or sentence, which is minimal in terms of data exposure. If this is unacceptable for your use case, local TTS alternatives are discussed in Chapter 5.*

### Privacy

Language learning vocabulary reveals information about a person's interests, proficiency level, travel plans, and cultural engagement. A cloud-based flashcard generation service would accumulate a detailed profile of each user's learning trajectory. Running locally means this data stays on your filesystem.

### Latency and Availability

Cloud API calls introduce network latency and depend on external service availability. Local inference through LM Studio has higher per-request latency (depending on your hardware), but it has zero network overhead and is available whenever your machine is on. There are no rate limits, no API quotas, and no degraded-service windows.

### Cost

Cloud LLM APIs charge per token. If you're generating flashcards for hundreds of vocabulary items, the costs add up. Local inference has a one-time hardware cost (a capable GPU) and zero marginal cost per request. For a tool intended to be used daily as part of a language learning routine, the economics of local inference are favorable.

### Control

Running your own model means you can swap it out. If a new model handles Japanese better, you load it into LM Studio and the rest of the pipeline is unchanged. You are not locked into a provider's model selection, pricing, or deprecation schedule.

## System Architecture

The system is structured as a **linear pipeline** — each stage takes input from the previous stage and produces output for the next. There are no branches, no conditional paths, and no feedback loops. This is the simplest possible architecture for a multi-stage system, and it is chosen deliberately.

### Pipeline Stages

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  retriever   │────▶│     llm      │────▶│     tts      │────▶│  flashcard   │────▶│ anki_connect │
│             │     │             │     │             │     │             │     │             │
│  jamdict    │     │  LM Studio  │     │  edge-tts   │     │  formatting │     │  AnkiConnect│
│  lookup     │     │  inference  │     │  synthesis  │     │  assembly   │     │  API        │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
     dict               dict              file paths           dict               note ID
```

Each module is a Python file in the `modules/` directory with a single public function:

| Module | Function | Input | Output |
|--------|----------|-------|--------|
| `retriever.py` | `lookup(word)` | Japanese string | Dict of readings, meanings, kanji info |
| `llm.py` | `generate_examples(vocab_info)` | Dict from retriever | Dict with example sentence, translation, gloss |
| `tts.py` | `generate_audio(text, filename)` | Text + filename | File path to generated .mp3 |
| `flashcard.py` | `build_flashcard(vocab_info, llm_output, audio_paths)` | Dicts from prior stages | Dict with front/back HTML fields |
| `anki_connect.py` | `add_note(flashcard)` | Dict from flashcard module | Integer note ID |

### Data Flow

The data flowing through the pipeline accumulates rather than transforms. The retriever produces dictionary data; the LLM module *adds* generated content to it rather than replacing it; the TTS module *adds* audio file paths; the flashcard module *combines* everything into a presentation format; and the AnkiConnect module *delivers* the result.

This accumulative pattern means that each stage has access to all upstream data. The flashcard module can reference both the dictionary readings (from stage 1) and the generated sentence (from stage 2) when constructing the card. This is implemented simply by passing multiple arguments to downstream functions rather than trying to merge everything into a single evolving data structure.

### Module Boundaries

Each module depends on at most the Python standard library, its own specific third-party package, and the shared `config.py` file. Some modules use all three; `flashcard.py` uses none of them — it is a pure data transformation with zero imports. No module imports another module. The orchestration happens entirely in `main.py`, which imports all five modules and calls them in sequence.

This means any module can be tested, replaced, or modified in isolation. If you wanted to swap `jamdict` for a different dictionary backend, you would rewrite `retriever.py` to return the same dict shape and nothing else would change. If you wanted to use a cloud LLM instead of LM Studio, you would rewrite `llm.py`. The interface contracts are the dict shapes, not the implementations.

### Error Handling Strategy

Errors in this pipeline are **fail-fast**. If the dictionary lookup finds no results, the program exits immediately with a message. If LM Studio is not running, the program exits. If AnkiConnect is not reachable, the program exits. There is no retry logic, no fallback behavior, and no partial output.

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

## What's Next

The remaining chapters move from environment setup through each layer of the pipeline, building up to the fully integrated system.

- **Chapter 2: Environment Setup** — Configuring the Python environment, installing dependencies, setting up LM Studio, Anki with AnkiConnect, and all other tooling required to develop and run the project.
- **Chapter 3: Retrieval** — Implementing the dictionary lookup module. Covers the JMdict and KANJIDIC2 data sources, the `jamdict` library, and the query logic for retrieving exact definitions, readings, and kanji metadata. This retrieved data forms the deterministic ground truth that anchors the generative stages.
- **Chapter 4: Generative Logic** — Running LLMs locally for structured text generation. Covers model selection and quantization trade-offs, inference server setup with LM Studio, prompt engineering for consistent JSON output, and fallback strategies.
- **Chapter 5: Local Media Generation** — Implementing text-to-speech audio synthesis with edge-tts. Covers async audio generation, normalization standards, and handling of file paths for media linkage in Anki.
- **Chapter 6: Flashcard Construction and Anki Injection** — Assembling the outputs from prior stages into Anki-compatible flashcard fields, and delivering them via the AnkiConnect protocol including media file storage.
- **Chapter 7: End-to-End Integration** — The final technical chapter. Covers orchestration of all components into a single CLI pipeline, error handling across service boundaries, latency considerations, and construction of the final payload for injection into Anki.
- **Chapter 8: Conclusion and Future Work** — Summary of the implemented architecture, local vs. cloud trade-offs, and suggestions for technical extensions.
