# Chapter 3: Retrieval

This chapter covers the first stage of the pipeline — looking up a Japanese word in a local dictionary database and extracting structured data from the result. The retrieval module produces the deterministic ground truth that every downstream stage depends on.

## The Data Sources

The retrieval module queries two databases, both accessed through the `jamdict` Python library:

**JMdict** (Japanese-Multilingual Dictionary) is a machine-readable Japanese-English dictionary maintained by the Electronic Dictionary Research and Development Group (EDRDG). It has been actively maintained since 1991 and contains over 200,000 entries. Each entry includes:

- Kanji representations of the word (e.g., 食べる)
- Kana readings (e.g., たべる)
- Sense groups, each containing English glosses, part-of-speech tags, usage notes, and field/dialect markers

JMdict is the data source behind most Japanese-English dictionary apps and websites. If you have used Jisho.org, you have queried JMdict.

**KANJIDIC2** is a companion database containing information about individual kanji characters. For each of the 13,000+ kanji it covers, it provides:

- On'yomi and kun'yomi readings
- English meanings
- Stroke count
- Radical classification
- Grade level and JLPT level
- Unicode code point

These two databases serve different lookup patterns. When a user enters a multi-character word like 食べる, JMdict provides the vocabulary-level data (readings and definitions of the word as a unit). When the input is a single kanji like 食, KANJIDIC2 provides character-level data (all readings of that character, its component radicals, its standalone meanings). The retrieval module handles both cases.

## jamdict

### What It Does for Us

`jamdict` is a Python package that bundles JMdict and KANJIDIC2 into a local SQLite database and provides a query API on top of it. Without `jamdict`, we would need to:

1. Download the raw XML files from EDRDG (JMdict is ~75 MB of XML)
2. Parse the XML into a usable structure
3. Build a local database or index for efficient querying
4. Write query logic to search by kanji, kana, or English gloss

`jamdict` does all of this. The companion package `jamdict-data` ships the pre-built SQLite database (~54 MB compressed), and the `Jamdict` class provides a `lookup()` method that searches across both JMdict and KANJIDIC2 simultaneously.

### The Lookup Result Object

The entry point to `jamdict` is `Jamdict.lookup()`. It returns a `LookupResult` object with three attributes:

```python
from jamdict import Jamdict
jmd = Jamdict()
result = jmd.lookup("食べる")
```

- `result.entries` — A list of JMdict entries matching the query. Each entry is a vocabulary item with kanji forms, kana forms, and sense groups.
- `result.chars` — A list of KANJIDIC2 character entries for any kanji found in the query string. For 食べる, this would include the entry for 食.
- `result.names` — A list of JMnedict (Japanese Names Dictionary) entries. We don't use this.

The lookup is flexible — it searches kanji forms, kana forms, and English glosses. Searching for `食べる`, `たべる`, or `eat` all return results (though the result sets differ).

### Navigating JMdict Entries

A JMdict entry has a nested structure that reflects how Japanese vocabulary works. A single dictionary entry can have multiple written forms, multiple readings, and multiple distinct meanings.

```python
entry = result.entries[0]

# Kanji forms — the ways this word can be written
entry.kanji_forms   # [食べる]

# Kana forms — the pronunciation(s)
entry.kana_forms    # [たべる]

# Senses — distinct meanings, each with glosses
entry.senses        # [SenseGroup(...), SenseGroup(...), ...]
```

Each sense group contains:

- `gloss` — A list of `Gloss` objects, each with a `text` attribute containing an English definition
- `pos` — Part of speech tags (e.g., "Ichidan verb", "transitive verb")
- `misc` — Usage notes
- `field` — Subject field tags (e.g., "computing", "medicine")

For our purposes, we extract two things from entries: all unique kana readings, and all unique English glosses across all senses. The part-of-speech and field data is available but not used in the current flashcard format.

### Navigating KANJIDIC2 Characters

A KANJIDIC2 character entry provides data about a single kanji:

```python
char = result.chars[0]

char.literal        # "食" — the character itself

# Reading-meaning groups
rm = char.rm_groups[0]
rm.readings         # [Reading("ショク"), Reading("ジキ"), Reading("く.う"), ...]
rm.meanings         # [Meaning("eat"), Meaning("food"), ...]
```

Meanings in KANJIDIC2 are tagged by language. The database includes meanings in English, French, Spanish, and Portuguese. We filter for English meanings only using the `m_lang` attribute:

```python
english_meanings = [m.value for m in rm.meanings if m.m_lang == "en"]
```

The `m_lang` attribute is `"en"` for English meanings. Non-English meanings have their respective language codes.

## Implementation

The full module:

```python
from jamdict import Jamdict

jmd = Jamdict()


def lookup(word: str) -> dict:
    """Look up a Japanese word using jamdict (JMdict + KANJIDIC2)."""
    result = jmd.lookup(word)

    if not result.entries and not result.chars:
        raise ValueError(f"No results found for '{word}'")

    readings = []
    meanings = []

    for entry in result.entries:
        for kana in entry.kana_forms:
            if str(kana) not in readings:
                readings.append(str(kana))
        for sense in entry.senses:
            for gloss in sense.gloss:
                if str(gloss) not in meanings:
                    meanings.append(str(gloss))

    kanji_info = None
    if result.chars:
        char = result.chars[0]
        kanji_info = {
            "literal": char.literal,
            "meanings": [m.value for m in char.rm_groups[0].meanings if m.m_lang == "en"] if char.rm_groups else [],
            "readings": [r.value for r in char.rm_groups[0].readings] if char.rm_groups else [],
        }

    return {
        "word": word,
        "readings": readings,
        "meanings": meanings,
        "kanji_info": kanji_info,
    }
```

### Module-Level Initialization

```python
jmd = Jamdict()
```

The `Jamdict` instance is created at module level, outside any function. This means the database connection is established once when the module is first imported, not on every call to `lookup()`. For a CLI tool that processes one word per invocation this makes no practical difference, but it is the correct pattern — `Jamdict()` locates the SQLite database file and opens a connection, and there is no reason to repeat that work.

### Input Handling

The function takes a single string and passes it directly to `jmd.lookup()`. There is no input normalization, no romaji-to-kana conversion, and no fuzzy matching. The user is expected to provide the word in Japanese script (kanji, hiragana, or katakana). This is a deliberate choice — the retrieval module is not the place for input preprocessing. If the input produces no results, the function raises a `ValueError` with the original query, and `main.py` catches it and exits.

### Extracting Readings

```python
readings = []
for entry in result.entries:
    for kana in entry.kana_forms:
        if str(kana) not in readings:
            readings.append(str(kana))
```

A lookup can return multiple JMdict entries (homonyms, related forms), and each entry can have multiple kana forms. We flatten all of them into a single deduplicated list. The `str()` call converts `jamdict`'s `KanaForm` object to a plain string.

The deduplication uses a linear scan (`if str(kana) not in readings`) rather than a set. This preserves insertion order — the first entry's readings appear first, which is typically the most common reading. With Japanese vocabulary, the number of readings for a given word is small (usually 1–3), so the O(n) membership check is not a concern.

### Extracting Meanings

```python
meanings = []
for entry in result.entries:
    for sense in entry.senses:
        for gloss in sense.gloss:
            if str(gloss) not in meanings:
                meanings.append(str(gloss))
```

The same pattern applies to meanings. A JMdict entry groups its English definitions into "senses" — distinct meaning clusters. The word 食べる has two senses:

1. "to eat" (the literal meaning)
2. "to live on (e.g. a salary), to live off, to subsist on" (the figurative meaning)

Each sense can have multiple glosses (synonymous English translations). We flatten everything into a single list because the flashcard format does not distinguish between senses — the back of the card shows all meanings as a combined list. The LLM module receives this same list and uses it to understand the word's semantic range when generating example sentences.

### Extracting Kanji Info

```python
kanji_info = None
if result.chars:
    char = result.chars[0]
    kanji_info = {
        "literal": char.literal,
        "meanings": [m.value for m in char.rm_groups[0].meanings if m.m_lang == "en"] if char.rm_groups else [],
        "readings": [r.value for r in char.rm_groups[0].readings] if char.rm_groups else [],
    }
```

If the query contains kanji, `result.chars` will be populated with KANJIDIC2 entries. We take only the first character's data. For a single-kanji query like 食, this gives us the full character entry. For a multi-character word like 食べる, this gives us data for 食 (the first kanji).

The `rm_groups` (reading-meaning groups) list is checked for emptiness before indexing. In practice, every kanji in KANJIDIC2 has at least one reading-meaning group, but the defensive check costs nothing and prevents an `IndexError` on malformed data.

The `m_lang == "en"` filter on meanings excludes non-English glosses. KANJIDIC2 includes French, Spanish, and Portuguese translations for many characters, and without this filter they would be mixed into the English meanings list.

### The Output Dict

```python
return {
    "word": word,
    "readings": readings,
    "meanings": meanings,
    "kanji_info": kanji_info,
}
```

The function returns a plain dict with four keys. This dict is the interface contract between the retrieval module and every downstream module. The LLM module reads `word`, `readings`, and `meanings` to construct its prompt. The flashcard module reads `word` and `readings` to build the front of the card.

`kanji_info` is `None` for words that contain no kanji (pure kana words like おはよう). Downstream modules check for this and handle it accordingly.

The dict uses plain Python types — strings and lists of strings. There are no custom classes, no dataclasses, no type wrappers. This keeps the interface simple and makes the data easy to inspect during debugging (just `print()` the dict).

## What the Data Looks Like

### Vocabulary Lookup

```python
>>> from modules.retriever import lookup
>>> import json
>>> print(json.dumps(lookup("食べる"), indent=2, ensure_ascii=False))
{
  "word": "食べる",
  "readings": ["たべる"],
  "meanings": [
    "to eat",
    "to live on (e.g. a salary)",
    "to live off",
    "to subsist on"
  ],
  "kanji_info": {
    "literal": "食",
    "meanings": ["eat", "food"],
    "readings": ["ショク", "ジキ", "く.う", "く.らう", "た.べる", "は.む"]
  }
}
```

### Single Kanji Lookup

```python
>>> print(json.dumps(lookup("輪"), indent=2, ensure_ascii=False))
{
  "word": "輪",
  "readings": ["わ"],
  "meanings": [
    "ring",
    "circle",
    "link",
    "wheel",
    ...
  ],
  "kanji_info": {
    "literal": "輪",
    "meanings": ["wheel", "ring", "circle", "link", ...],
    "readings": ["リン", "わ"]
  }
}
```

For a single kanji, both `meanings` (from JMdict, word-level) and `kanji_info.meanings` (from KANJIDIC2, character-level) are populated. They overlap but are not identical — JMdict meanings reflect how the character is used as a standalone word, while KANJIDIC2 meanings reflect the character's semantic range across all compounds.

### Kana-Only Word

```python
>>> print(json.dumps(lookup("おはよう"), indent=2, ensure_ascii=False))
{
  "word": "おはよう",
  "readings": ["おはよう"],
  "meanings": ["good morning"],
  "kanji_info": null
}
```

No kanji in the query means no KANJIDIC2 data. `kanji_info` is `None`.

## Role in the Pipeline

The retrieval module is the only stage in the pipeline that touches a curated, authoritative data source. Everything after it is either generated (LLM, TTS) or mechanical (flashcard formatting, AnkiConnect delivery). This is why it runs first — it establishes the factual foundation that the generative stages build on.

The readings and meanings from this module appear directly on the finished flashcard. They are not paraphrased, summarized, or transformed by the LLM. The LLM receives them as input context and generates *additional* content (example sentences), but the dictionary data passes through to the card unchanged. This is the architectural principle from Chapter 1 in practice: deterministic data for correctness, generative data for enrichment.

If `lookup()` raises a `ValueError` (no results found), the pipeline halts immediately. There is no point in asking the LLM to generate an example sentence for a word that does not exist in the dictionary, and there is no point in generating audio for a word we cannot define. The fail-fast behavior here prevents the downstream modules from producing confident-looking but ungrounded output — exactly the kind of error that a hybrid architecture is designed to avoid.
