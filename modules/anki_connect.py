import base64
import json
import os
import requests
import config


def _invoke(action: str, **params) -> dict:
    """Send a request to AnkiConnect."""
    payload = {"action": action, "version": 6, "params": params}
    try:
        resp = requests.post(config.ANKI_CONNECT_URL, json=payload, timeout=10)
        resp.raise_for_status()
    except requests.ConnectionError:
        raise ConnectionError(
            "Cannot connect to AnkiConnect. "
            "Is Anki open with the AnkiConnect add-on installed?"
        )
    result = resp.json()
    if result.get("error"):
        raise RuntimeError(f"AnkiConnect error: {result['error']}")
    return result["result"]


def ensure_deck_exists(deck_name: str) -> None:
    """Create the deck if it doesn't already exist."""
    _invoke("createDeck", deck=deck_name)


def _store_media(filepath: str, filename: str) -> None:
    """Store an audio file in Anki's media folder via AnkiConnect."""
    with open(filepath, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    _invoke("storeMediaFile", filename=filename, data=data)


def add_note(flashcard: dict) -> int:
    """Add a note to Anki and store associated audio files."""
    ensure_deck_exists(config.ANKI_DECK_NAME)

    # Store audio files in Anki's media folder
    audio_paths = flashcard.get("audio_paths", {})
    if audio_paths.get("word_path"):
        _store_media(audio_paths["word_path"], audio_paths["word_filename"])
    if audio_paths.get("sentence_path"):
        _store_media(audio_paths["sentence_path"], audio_paths["sentence_filename"])

    note = {
        "deckName": config.ANKI_DECK_NAME,
        "modelName": config.ANKI_NOTE_TYPE,
        "fields": {
            "Front": flashcard["front"],
            "Back": flashcard["back"],
        },
        "options": {
            "allowDuplicate": False,
        },
    }

    return _invoke("addNote", note=note)
