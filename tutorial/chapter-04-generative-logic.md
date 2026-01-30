# Chapter 4: Generative Logic

This chapter covers the second stage of the pipeline — sending the dictionary data from the retrieval module to a locally-hosted large language model and getting back structured, machine-parsable output. The chapter is organized around three topics: selecting and quantizing a model, setting up the inference server, and engineering prompts that produce reliable structured output.

## Model Selection and Quantization

### What We Need from the Model

The task we are asking the model to perform is narrow:

1. Read a Japanese word, its readings, and its English definitions
2. Write one natural Japanese sentence using that word
3. Translate that sentence to English
4. Produce a concise English gloss

This is not a difficult task by LLM standards. It does not require long-context reasoning, multi-step logic, or specialized domain knowledge. What it does require is:

- **Japanese language competence** — the model must generate grammatically correct, natural-sounding Japanese
- **Instruction following** — the model must return JSON with the exact keys we specify, not a conversational response
- **Bilingual alignment** — the English translation must actually correspond to the Japanese sentence

These requirements constrain model selection more than raw parameter count does. A 70B model that was trained primarily on English will perform worse at this task than a 7B model with strong multilingual training data.

### Recommended Models

Models that work well for this task, listed by parameter count:

| Model | Parameters | Japanese Quality | Notes |
|-------|-----------|-----------------|-------|
| [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) | 7B | Excellent | Strong multilingual training, reliable JSON output |
| [Qwen2.5-14B-Instruct](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct) | 14B | Excellent | Better sentence variety, needs more VRAM |
| [Mistral-7B-Instruct](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3) | 7B | Good | Solid instruction following, occasionally awkward Japanese |
| [Llama-3.1-8B-Instruct](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct) | 8B | Good | Reliable structured output, Japanese is functional but not native-quality |
| [Gemma-2-9B-Instruct](https://huggingface.co/google/gemma-2-9b-it) | 9B | Good | Google's multilingual model, good balance |

The Qwen2.5 family is the strongest recommendation for this specific task. Alibaba's training data includes substantial Chinese and Japanese text, and the instruction-tuned variants follow JSON output instructions consistently.

### Quantization

LLMs in their original form use 16-bit floating point weights (FP16 or BF16). A 7B-parameter model at full precision requires approximately 14 GB of memory — each parameter is 2 bytes. Quantization reduces the precision of these weights to use fewer bits per parameter, reducing memory requirements at the cost of some output quality.

#### How Quantization Works

Quantization maps the continuous range of weight values to a smaller set of discrete levels. In 4-bit quantization, each weight is represented by one of 16 possible values instead of one of 65,536 (FP16). The quantization algorithm chooses these 16 levels to minimize the information loss for each layer of the model.

Modern quantization methods (GPTQ, AWQ, and the [GGUF format](https://github.com/ggerganov/llama.cpp) used by llama.cpp and LM Studio) apply quantization non-uniformly — more important layers or weight matrices may be kept at higher precision while less sensitive ones are quantized more aggressively. This is why you see labels like `Q4_K_M` rather than a simple "4-bit": the `K` indicates k-quant grouping, and the `M` indicates a "medium" mix of precisions across layers.

#### Quantization Levels

When downloading a model in LM Studio, you choose a quantization variant. Common levels and their trade-offs:

| Quant | Bits/Weight | 7B Model Size | Quality Impact | Use Case |
|-------|-------------|---------------|----------------|----------|
| Q2_K | ~2.5 | ~3 GB | Significant degradation | Not recommended |
| Q3_K_M | ~3.5 | ~3.5 GB | Noticeable, especially in Japanese | Tight VRAM budget |
| Q4_K_M | ~4.5 | ~4.5 GB | Minor, usually acceptable | **Best default choice** |
| Q5_K_M | ~5.5 | ~5.5 GB | Minimal | Good quality/size balance |
| Q6_K | ~6.5 | ~6.5 GB | Negligible | When you have the VRAM |
| Q8_0 | 8 | ~7.5 GB | Near-original | Quality-sensitive tasks |
| FP16 | 16 | ~14 GB | None (original) | Research, comparison |

For this project, **Q4_K_M is the recommended default**. The quality difference between Q4_K_M and FP16 is minimal for a sentence-generation task — quantization artifacts tend to manifest in subtle reasoning errors and long-range coherence, neither of which matters when generating a single example sentence. The memory savings are substantial: a 7B model at Q4_K_M fits comfortably in 8 GB of VRAM with room for context.

#### VRAM Planning

The model must fit in GPU VRAM for reasonable inference speed. CPU inference works but is 10–20x slower, which makes the tool frustrating to use interactively.

Rough memory budget for inference:

```
Total VRAM needed ≈ Model size + KV cache + overhead
                  ≈ Model size × 1.2  (for short contexts)
```

| GPU VRAM | Recommended Configuration |
|----------|--------------------------|
| 6 GB | 7B model at Q3_K_M or Q4_K_M |
| 8 GB | 7B model at Q4_K_M or Q5_K_M |
| 12 GB | 7B at Q8_0, or 14B at Q4_K_M |
| 16 GB | 14B at Q5_K_M or Q6_K |
| 24 GB | 14B at Q8_0, or larger models |

Our prompts are short (under 200 tokens of context) and the expected output is short (under 100 tokens), so KV cache memory is negligible. The model weights are the dominant factor.

If you don't have a dedicated GPU, LM Studio can offload layers to CPU RAM. Set the GPU offload slider to match your available VRAM — LM Studio will keep that many layers on the GPU and run the rest on CPU. Partial offloading is significantly faster than pure CPU inference.

## Inference Server Setup

### LM Studio's Local Server

LM Studio includes a built-in inference server that exposes an OpenAI-compatible API. This is what our code talks to. The server:

- Listens on `http://localhost:1234` by default
- Implements the `/v1/chat/completions` endpoint (and others)
- Accepts the same JSON request format as OpenAI's API
- Returns the same JSON response format

This compatibility is the reason we can use the `requests` library directly rather than needing an LM Studio-specific client. Any code written against the OpenAI chat completions API works with LM Studio with no modifications beyond changing the base URL.

### Starting the Server

In LM Studio:

1. Load a model (discussed in the previous section and in Chapter 2)
2. Navigate to the **Local Server** tab
3. Click **Start Server**

The server logs will show the port and which model is loaded. The default port is 1234. If you change it, update `config.py`:

```python
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
```

### The Chat Completions API

Our module sends POST requests to the chat completions endpoint. The request format:

```json
{
  "model": "local-model",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "response_format": {"type": "json_object"},
  "temperature": 0.7
}
```

**`model`** — LM Studio requires this field but ignores its value. It always routes to whatever model is currently loaded. We set it to `"local-model"` as a placeholder. This is a quirk of LM Studio's OpenAI compatibility layer — the field must be present to satisfy request validation, but LM Studio is a single-model server.

**`messages`** — The conversation history. We use two messages: a system prompt that defines the task and output format, and a user message containing the vocabulary data. The chat completions format (as opposed to a raw text completion) gives us the system/user role distinction, which most instruction-tuned models are trained to respect.

**`response_format`** — Requests structured JSON output. This is covered in detail in the prompt engineering section below.

**`temperature`** — Controls randomness. At 0.0, the model always picks the highest-probability token. At 1.0, it samples proportionally from the probability distribution. We use 0.7 — high enough to get varied, natural-sounding sentences across multiple runs, low enough to avoid incoherent output. For a sentence generation task, some randomness is desirable: you don't want every flashcard for 食べる to have the same example sentence.

### The Response Format

LM Studio returns a response matching the OpenAI format:

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "{\"example_sentence\": \"...\", ...}"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 85,
    "completion_tokens": 42,
    "total_tokens": 127
  }
}
```

The generated text is in `choices[0].message.content`. When `response_format` is active and supported, this string is guaranteed to be valid JSON. When it is not, the string is the model's raw output — which may or may not be valid JSON, and may include markdown fences or other formatting.

## Prompt Engineering

### The System Prompt

```python
system_prompt = (
    "You are a Japanese language teaching assistant. "
    "You will be given a Japanese word with its readings and meanings. "
    "Return a JSON object with exactly these keys:\n"
    '- "example_sentence": a natural Japanese example sentence using the word\n'
    '- "example_sentence_translation": the English translation of the example sentence\n'
    '- "vocab_translation": a concise English meaning (2-5 words)\n'
    "Return ONLY valid JSON, no other text."
)
```

The system prompt does three things:

**1. Sets the role.** "You are a Japanese language teaching assistant" activates the model's instruction-following behavior and biases it toward pedagogically appropriate output. Without a role, some models default to a more conversational style.

**2. Defines the output schema.** The three keys are listed explicitly with descriptions. This is not a formal JSON schema — it is a natural language description of one. For small, fixed output structures, listing the keys directly in the prompt is more reliable than referencing an external schema definition. The model sees exactly what it needs to produce.

**3. Constrains the output format.** "Return ONLY valid JSON, no other text" prevents the model from wrapping its response in conversational framing ("Here's an example sentence for you:") or markdown formatting. This instruction is partially redundant with `response_format`, but it matters when `response_format` is not supported and the model must self-constrain.

### Injecting the Ground Truth

```python
user_prompt = f"Word: {word}\nReadings: {readings}\nMeanings: {meanings}"
```

The user message injects the retrieval module's output — the deterministic ground truth — into the model's context. This is the point where the two layers of the hybrid architecture connect.

The format is deliberately simple: labeled fields separated by newlines. More structured formats (XML tags, JSON input) are unnecessary here because the model is not extracting data from a complex document. It is reading three short, clearly labeled values.

Note what we send and what we do not:

- **Sent**: `word`, `readings`, `meanings` — everything the model needs to understand the vocabulary item and write a sentence with it
- **Not sent**: `kanji_info` — character-level data (radicals, stroke counts, individual kanji readings) is useful on the flashcard but is not useful for sentence generation. Sending it would add noise to the prompt without improving output quality.

This is a general principle: **give the model exactly the context it needs and nothing more.** Extra context does not help and can distract, especially with smaller models that have limited attention capacity.

### Structured Output: `response_format`

```python
"response_format": {"type": "json_object"}
```

The `response_format` parameter is an [OpenAI API feature](https://platform.openai.com/docs/api-reference/chat/create#chat-create-response_format) that constrains the model's output to valid JSON. When active, the inference engine modifies the sampling process to ensure that every generated token produces a valid JSON string. Specifically:

- The output always begins with `{` or `[`
- String values are properly quoted and escaped
- The output always ends with a matching closing brace/bracket
- Generation stops when the JSON structure is complete

This is implemented at the inference engine level, not in the model's weights. The engine maintains a state machine that tracks the JSON structure being generated and masks out tokens that would produce invalid JSON at each step. The model still chooses *which* valid JSON to produce, but it cannot produce non-JSON output.

#### The Fallback Problem

Not all models support `response_format`. Some model architectures or quantization formats are served by inference backends that do not implement constrained decoding. When this happens, LM Studio returns a `400 Bad Request` error.

Our code handles this with a fallback:

```python
resp = requests.post(config.LM_STUDIO_URL, json=payload, timeout=60)
if resp.status_code == 400:
    payload.pop("response_format")
    resp = requests.post(config.LM_STUDIO_URL, json=payload, timeout=60)
```

If the first request fails with a 400, we remove `response_format` and retry. The system prompt's instruction to "Return ONLY valid JSON, no other text" is now the only constraint. Most instruction-tuned models follow this instruction reliably, but without engine-level enforcement, there are two common failure modes:

**Markdown fences.** The model wraps its JSON in a code block:

````
```json
{"example_sentence": "...", ...}
```
````

**Conversational framing.** The model adds text around the JSON:

```
Here is the JSON output:
{"example_sentence": "...", ...}
```

The code handles the first case explicitly:

```python
content = content.strip()
if content.startswith("```"):
    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
```

This strips the opening fence line (including any language tag like `` ```json ``) and the closing fence, extracting the JSON between them. The second case (conversational framing) would cause `json.loads()` to raise a `JSONDecodeError`, which propagates as an unhandled exception. In practice, models that follow the system prompt well enough to produce valid JSON almost always produce *only* JSON, so this case is rare.

### Why Not a Full JSON Schema?

The OpenAI API (and some LM Studio configurations) supports a more powerful version of `response_format` that accepts a full JSON schema:

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "example_output",
    "schema": {
      "type": "object",
      "properties": {
        "example_sentence": {"type": "string"},
        "example_sentence_translation": {"type": "string"},
        "vocab_translation": {"type": "string"}
      },
      "required": ["example_sentence", "example_sentence_translation", "vocab_translation"]
    }
  }
}
```

This would guarantee not just valid JSON but the exact key names and types. We use the simpler `{"type": "json_object"}` for two reasons:

1. **Compatibility.** Schema-constrained decoding requires more sophisticated engine support. Many model/backend combinations that support basic JSON mode do not support full schema enforcement. Since we already need a fallback path for models that support neither, adding a third tier of complexity does not improve reliability.

2. **Sufficiency.** Our output structure has three string keys. The system prompt describes them unambiguously, and models follow the description with high fidelity. Schema enforcement solves a problem — key name variation, missing fields, wrong types — that we do not actually have in practice.

If you are adapting this architecture for a more complex output structure (nested objects, arrays of variable length, numeric fields), schema enforcement becomes more valuable and worth the compatibility trade-off.

## Implementation

The full module:

```python
import json
import requests
import config


def generate_examples(vocab_info: dict) -> dict:
    """Send vocab info to LM Studio and get example sentence + translation."""
    word = vocab_info["word"]
    readings = ", ".join(vocab_info["readings"])
    meanings = ", ".join(vocab_info["meanings"])

    system_prompt = (
        "You are a Japanese language teaching assistant. "
        "You will be given a Japanese word with its readings and meanings. "
        "Return a JSON object with exactly these keys:\n"
        '- "example_sentence": a natural Japanese example sentence using the word\n'
        '- "example_sentence_translation": the English translation of the example sentence\n'
        '- "vocab_translation": a concise English meaning (2-5 words)\n'
        "Return ONLY valid JSON, no other text."
    )

    user_prompt = f"Word: {word}\nReadings: {readings}\nMeanings: {meanings}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    payload = {
        "model": config.LM_STUDIO_MODEL,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
    }

    try:
        resp = requests.post(config.LM_STUDIO_URL, json=payload, timeout=60)
        # Fall back without response_format if the model doesn't support it
        if resp.status_code == 400:
            payload.pop("response_format")
            resp = requests.post(config.LM_STUDIO_URL, json=payload, timeout=60)
        resp.raise_for_status()
    except requests.ConnectionError:
        raise ConnectionError(
            f"Cannot connect to LM Studio at {config.LM_STUDIO_URL}. "
            "Is LM Studio running with a model loaded?"
        )

    content = resp.json()["choices"][0]["message"]["content"]
    # Extract JSON from the response, handling markdown fences
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(content)
```

### Connection Handling

```python
try:
    resp = requests.post(config.LM_STUDIO_URL, json=payload, timeout=60)
    ...
except requests.ConnectionError:
    raise ConnectionError(
        f"Cannot connect to LM Studio at {config.LM_STUDIO_URL}. "
        "Is LM Studio running with a model loaded?"
    )
```

The `timeout=60` is generous. Local inference for a short prompt typically completes in 2–10 seconds on a GPU, but slower hardware (CPU inference, heavily quantized large models) can take longer. Sixty seconds prevents the tool from hanging indefinitely if the server accepts the connection but never responds, while leaving headroom for slow hardware.

The `ConnectionError` catch specifically targets the case where LM Studio is not running at all — the TCP connection is refused. HTTP errors (400, 500) are handled separately by the fallback logic and `raise_for_status()`. This distinction matters for the error message: a connection refusal means "start LM Studio," while a 500 error means "the model crashed during inference," and the user needs different instructions for each.

### Response Parsing

```python
content = resp.json()["choices"][0]["message"]["content"]
content = content.strip()
if content.startswith("```"):
    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
return json.loads(content)
```

The parsing is straightforward: extract the content string, strip whitespace, handle markdown fences if present, and parse as JSON. The `json.loads()` call returns a plain Python dict, which is the module's output.

If the JSON is malformed — missing keys, invalid syntax, truncated output — `json.loads()` raises a `JSONDecodeError`. This is not caught here; it propagates to `main.py` and terminates the pipeline. This is intentional: a malformed LLM response indicates either a model quality issue or a prompt problem, both of which require human attention rather than automated recovery.

## What the Output Looks Like

A successful call returns a dict with three keys:

```python
>>> from modules.llm import generate_examples
>>> vocab_info = {
...     "word": "食べる",
...     "readings": ["たべる"],
...     "meanings": ["to eat", "to live on (e.g. a salary)", "to live off", "to subsist on"],
...     "kanji_info": None
... }
>>> generate_examples(vocab_info)
{
    "example_sentence": "彼は毎日ご飯を食べます。",
    "example_sentence_translation": "He eats rice every day.",
    "vocab_translation": "to eat"
}
```

The `vocab_translation` field is a concise gloss derived from the full meaning list. Where the retrieval module returns all dictionary senses ("to eat, to live on (e.g. a salary), to live off, to subsist on"), the LLM distills this to the primary meaning ("to eat"). This concise form works better on a flashcard than a raw list of dictionary senses.

The `example_sentence` is generated, not retrieved. Running the same query again may produce a different sentence. This is desirable — if you delete and re-create a flashcard, you get fresh content rather than a duplicate.

## Relationship to the Retrieval Layer

This module consumes the output of `retriever.py` and uses it as prompt context. The relationship between the two modules embodies the hybrid architecture:

- The retriever provides **facts** — what the word means, how it is read
- The LLM provides **creative content** — an example of the word in use

The LLM does not verify or override the retriever's data. It receives the meanings as context and uses them to inform its sentence generation, but the meanings themselves pass through to the flashcard unchanged (via the `vocab_info` dict that `main.py` holds). If the LLM generates a sentence that uses the word in a different sense than the primary meaning, the dictionary definitions on the flashcard provide a corrective reference point.

This is the practical benefit of the hybrid approach: the generated content does not need to be perfect because it is always presented alongside authoritative data. The learner sees the dictionary definition *and* the example sentence, and can evaluate one against the other.
