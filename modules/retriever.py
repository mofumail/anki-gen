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
    # Check if the word is a single kanji or extract kanji info from chars
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
