def build_flashcard(vocab_info: dict, llm_output: dict, audio_paths: dict) -> dict:
    """Combine all data into a flashcard dict with front and back fields."""
    word = vocab_info["word"]
    reading = ", ".join(vocab_info["readings"]) if vocab_info["readings"] else ""
    meaning = llm_output["vocab_translation"]
    example = llm_output["example_sentence"]
    example_translation = llm_output["example_sentence_translation"]

    word_audio_tag = f'[sound:{audio_paths["word_filename"]}]' if audio_paths.get("word_filename") else ""
    sentence_audio_tag = f'[sound:{audio_paths["sentence_filename"]}]' if audio_paths.get("sentence_filename") else ""

    front = f"{word} ({reading}) {word_audio_tag}".strip()

    back_parts = [
        meaning,
        "",
        f"{example} {sentence_audio_tag}".strip(),
        example_translation,
    ]
    back = "<br>".join(back_parts)

    return {
        "front": front,
        "back": back,
        "audio_paths": audio_paths,
    }
