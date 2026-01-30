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
