import asyncio
import os
import sys
import edge_tts
import config

VOICE = "ja-JP-NanamiNeural"

# Fix asyncio ProactorEventLoop RuntimeError on Windows Python 3.8
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _generate(text: str, filepath: str) -> None:
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(filepath)


def generate_audio(text: str, filename: str) -> str:
    """Generate a Japanese TTS audio file and return its path."""
    os.makedirs(config.AUDIO_DIR, exist_ok=True)
    filepath = os.path.join(config.AUDIO_DIR, filename)
    asyncio.run(_generate(text, filepath))
    return filepath
