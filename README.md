# Anki Japanese Flashcard Generator

A technical tutorial on building a hybrid AI system that generates Japanese-language flashcards using local infrastructure.

## What This Is

This tutorial walks through building a CLI tool that takes a Japanese word and produces a complete Anki flashcard with dictionary definitions, an LLM-generated example sentence, and synthesized audio — all running locally.

```
python main.py 食べる
```

## Chapters

| Chapter | Topic |
|---------|-------|
| [1. Introduction](chapter-01-introduction.md) | Architectural overview, hybrid AI, local-first design |
| [2. Environment Setup](chapter-02-environment-setup.md) | Python, dependencies, LM Studio, Anki + AnkiConnect |
| [3. Retrieval](chapter-03-retrieval.md) | Dictionary lookup with jamdict (JMdict/KANJIDIC2) |
| [4. Generative Logic](chapter-04-generative-logic.md) | Model selection, quantization, prompt engineering |
| [5. Local Media Generation](chapter-05-local-media-generation.md) | TTS audio synthesis with edge-tts |
| [6. Flashcard Construction & Anki](chapter-06-flashcard-construction-and-anki.md) | Card assembly and AnkiConnect delivery |
| [7. End-to-End Integration](chapter-07-end-to-end-integration.md) | Pipeline orchestration and error handling |
| [8. Conclusion & Future Work](chapter-08-conclusion.md) | Trade-offs, extensions, and next steps |

## Source Code

The complete source code is available in this repository. See [Chapter 2](chapter-02-environment-setup.md) for setup instructions.
