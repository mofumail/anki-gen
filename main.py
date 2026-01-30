import argparse
import os
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
