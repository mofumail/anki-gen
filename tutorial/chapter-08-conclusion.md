# Chapter 8: Conclusion and Future Work

## Summary

This tutorial walked through the design and implementation of a hybrid AI system that generates Japanese-language flashcards. 

### What Was Built

A CLI tool that accepts a Japanese word and produces a complete Anki flashcard with:

- Verified readings and definitions sourced from JMdict and KANJIDIC2
- A generated example sentence and English translation from a locally-hosted LLM
- Synthesized Japanese audio for both the word and the sentence
- Automatic insertion into Anki with embedded audio playback

The tool runs as a single command (`python main.py 食べる`) and completes in 3–15 seconds, depending primarily on LLM inference speed.

### Architecture

The system is a five-stage linear pipeline, each stage implemented as an independent Python module with a single public function:

| Stage | Module | Operation | Data Source |
|-------|--------|-----------|-------------|
| 1 | `retriever.py` | Dictionary lookup | Local SQLite (JMdict/KANJIDIC2) |
| 2 | `llm.py` | Sentence generation | Local LLM via LM Studio |
| 3 | `tts.py` | Audio synthesis | edge-tts (Microsoft TTS) |
| 4 | `flashcard.py` | Card assembly | In-memory transformation |
| 5 | `anki_connect.py` | Delivery to Anki | AnkiConnect localhost API |

Modules do not import each other. Data flows through plain Python dicts with implicit schema contracts. The orchestrator (`main.py`) calls each module in sequence and passes data forward. Errors are fail-fast, any failure terminates the pipeline immediately with an actionable message.

### Techniques

**Hybrid AI composition.** The core architectural idea: pair a deterministic retrieval system (jamdict/SQLite) with a probabilistic generative system (local LLM) such that correctness-critical data comes from the deterministic source and enrichment content comes from the generative source. The two layers are composed so that generated content is always presented alongside verified data, giving the end user a reliable reference point.

**Structured output from LLMs.** The LLM module uses a combination of system prompt engineering and the `response_format` API parameter to extract machine-parsable JSON from a language model. A fallback path handles models that do not support constrained decoding, with markdown fence stripping as a secondary parsing strategy.

**Async-to-sync bridging.** The TTS module wraps an async-only library (edge-tts) for use in a synchronous pipeline using `asyncio.run()`, with a platform-specific event loop policy fix for Windows.

**API protocol adaptation.** The AnkiConnect module implements a generic request helper (`_invoke`) that translates Python function calls into AnkiConnect's JSON-over-HTTP protocol, including base64 media encoding for file transfer.

### Software

| Component | Role | License |
|-----------|------|---------|
| Python 3.8+ | Runtime | PSF |
| jamdict + jamdict-data | Japanese dictionary access | MIT |
| edge-tts | Text-to-speech synthesis | MIT |
| requests | HTTP client | Apache 2.0 |
| LM Studio | Local LLM inference server | Proprietary (free) |
| Anki + AnkiConnect | Flashcard platform + API add-on | AGPL / GPL |

The project has four `pip install` dependencies. All other components (LM Studio, Anki) are external applications that the tool communicates with over localhost HTTP.

## Trade-offs: Local vs. Cloud

This project chose a local-first architecture. That choice has consequences worth examining honestly.

### Benefits of Local

**Privacy.** Vocabulary study data never leaves the machine. No third party accumulates a profile of what you are learning, how fast, or what you struggle with. For language learning this may seem low-stakes, but the principle extends to any domain where the input data is sensitive, medical terminology, legal vocabulary, proprietary jargon.

**Cost at scale.** After the one-time hardware investment (a GPU capable of running a 7B model), marginal cost per flashcard is zero. Cloud LLM APIs charge per token. If the tool is used daily over months of study, generating hundreds or thousands of flashcards, the cumulative API cost is non-trivial. Local inference amortizes the hardware cost across unlimited usage.

**Availability.** The tool works whenever the machine is on. No dependency on external service uptime, no degraded-service windows, no API deprecation notices. For a personal productivity tool embedded in a daily routine, reliability matters more than peak performance.

**Control.** Models can be swapped freely. If a new model handles Japanese better, you load it into LM Studio. No vendor approval, no migration, no API version changes. The inference server is a commodity interface, anything that serves the OpenAI chat completions format works.

### Benefits of Cloud

**Quality ceiling.** The best cloud-hosted models (GPT-4o, Claude, Gemini) produce higher-quality Japanese than any model you can run locally on consumer hardware. For complex vocabulary with nuanced usage patterns, a frontier model generates more natural example sentences with more accurate translations. If flashcard quality is the primary concern and privacy is not, a cloud model is the better choice.

**Setup simplicity.** The local stack requires installing LM Studio, downloading a model, understanding quantization trade-offs, and managing GPU memory. A cloud API requires an API key and a `requests.post()` call. For someone who wants the tool without the infrastructure, cloud is dramatically simpler.

**Hardware independence.** Local inference requires a GPU with sufficient VRAM. Not everyone has one. CPU inference works but is slow enough to make the tool frustrating for interactive use. Cloud APIs run on the provider's hardware and return results in 1–3 seconds regardless of the client machine.

**Multilingual TTS quality.** The one cloud dependency, edge-tts, exists precisely because local Japanese TTS alternatives do not match the quality of cloud-hosted neural voices without significant setup. A fully cloud-based architecture would not have this inconsistency.


## Future Work

The following extensions are technically feasible within the existing architecture. They are listed roughly in order of implementation complexity.

### Batch Processing

The current tool processes one word per invocation. A batch mode that accepts a word list would be straightforward:

```
python main.py --batch wordlist.txt
```

The pipeline would loop over words, with per-word error handling (skip failures, report at the end) replacing the current fail-fast behavior. The main consideration is LLM throughput, generating sentences for 100 words at one-word-per-request would take several minutes. Batching multiple words into a single LLM prompt ("Generate example sentences for these 10 words, returning a JSON array") would reduce the number of inference calls at the cost of more complex prompt engineering and output parsing.

### Custom Note Types

The tool currently uses Anki's built-in `Basic` note type with two fields. A custom note type with dedicated fields (Word, Reading, Meaning, Example Sentence, Example Translation, Word Audio, Sentence Audio) would enable:

- Separate styling per field (e.g., larger font for the word, smaller for the translation)
- Flexible card templates (e.g., show only the word on front, everything else on back)
- Reversed cards (English → Japanese) from the same note
- Cloze deletion cards that blank out the target word in the example sentence

AnkiConnect supports creating note types programmatically via the `createModel` action. The `flashcard.py` module would need to map data to the new field names, and `config.py` would reference the custom note type.

### Sentence Difficulty Calibration

The LLM prompt currently asks for "a natural Japanese example sentence" with no difficulty constraint. The prompt could be extended to specify a JLPT level or grammar complexity ceiling:

```
Generate an example sentence appropriate for JLPT N4 level
(use basic grammar, common vocabulary, polite form)
```

The difficulty target could be inferred from the word itself, JMdict includes JLPT level tags for many entries, and KANJIDIC2 includes grade levels for kanji. The retriever module already has access to this data; it would need to be surfaced in the output dict and forwarded to the LLM prompt.

### Symbolic Validation of Generated Sentences

An earlier design for this project included a dedicated validation stage between LLM generation and flashcard assembly. The idea was to run the generated Japanese sentence through a morphological analyzer, such as [MeCab](https://taku910.github.io/mecab/) or [Sudachi](https://github.com/WorksApplications/Sudachi), to decompose it into tokens with part-of-speech tags, dictionary forms, and reading annotations. This structured parse would enable automated checks: verifying that the target word actually appears in the sentence, calculating a difficulty score based on the grammar patterns and vocabulary used, and flagging sentences that exceed a target JLPT level.

This was scoped out of the current implementation for two reasons. First, the practical value is limited at the current scale of usage. When the tool generates one flashcard at a time and the user sees the sentence in the terminal output before it reaches Anki, manual inspection is a sufficient quality gate. The cost of symbolic validation, additional dependencies (MeCab requires a C library and a dictionary, Sudachi requires a Java runtime or its Rust port), platform-specific installation complexity, and the non-trivial logic of mapping morphological parses to difficulty metrics, is not justified by the error rate of modern instruction-tuned models on simple sentence generation tasks.

Second, difficulty calibration (discussed above) can be approximated through prompt engineering alone. Telling the model to use JLPT N4 grammar produces appropriately simple sentences in most cases. A morphological validator would catch the cases where the model ignores the constraint, but those cases are infrequent enough that the engineering effort is better spent elsewhere.

That said, symbolic validation becomes more compelling if the tool is extended to batch processing. When generating hundreds of flashcards unattended, manual inspection no longer scales, and an automated filter that rejects sentences exceeding a difficulty threshold or missing the target word would meaningfully improve output quality. An implementation would add a `validator.py` module between steps 2 and 3 in the pipeline, receiving the LLM output and the vocabulary info, and either passing the sentence through or requesting a regeneration. The module boundary is already clean enough to support this insertion without modifying adjacent modules.

### Local TTS Replacement

As discussed in Chapter 5, edge-tts is the one external network dependency. Replacing it with a fully local alternative would make the tool completely offline-capable. Candidates:

- **[VOICEVOX](https://voicevox.hiroshiba.jp/)**: Open-source Japanese TTS with a REST API, good voice quality, requires ~1–2 GB of disk space and a GPU for real-time synthesis
- **[Style-BERT-VITS2](https://github.com/litagin02/Style-Bert-VITS2)**: Higher quality but more complex setup, supports custom voice training
- **[Piper](https://github.com/rhasspy/piper)**: Lightweight, CPU-friendly TTS with Japanese voice support, lower quality than neural alternatives but fast and truly local

The `generate_audio(text, filename) -> path` interface was designed to make this substitution a contained change within `tts.py`.
