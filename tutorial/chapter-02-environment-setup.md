# Chapter 2: Environment Setup

This chapter covers installing and configuring before writing any application code. By the end, you will have a working Python environment with all dependencies, a local LLM inference server, and the Anki ecosystem ready to receive flashcards programmatically.

## Project Structure

Create a project directory and the following file layout:

```
anki/
├── main.py
├── config.py
├── requirements.txt
├── audio/
└── modules/
    ├── __init__.py
    ├── retriever.py
    ├── llm.py
    ├── tts.py
    ├── flashcard.py
    └── anki_connect.py
```

The `audio/` directory stores generated `.mp3` files. The `modules/` directory contains one Python file per pipeline stage. `config.py` holds all configuration constants. `main.py` is the CLI entry point that orchestrates everything.

```bash
mkdir anki
cd anki
mkdir modules audio
touch main.py config.py requirements.txt
touch modules/__init__.py modules/retriever.py modules/llm.py
touch modules/tts.py modules/flashcard.py modules/anki_connect.py
```

## Python

### Version Requirements

The project requires **Python 3.8 or later**. The code has been tested on Python 3.8 and 3.13.

Check your installed version:

```bash
python --version
```

On Windows, `python` may resolve to a Windows Store stub rather than an actual interpreter. If you get a "Python was not found" error or are redirected to the Microsoft Store, use `python3` or `py` instead:

```bash
python3 --version
py --version
```

If you need to install Python, download it from [python.org](https://www.python.org/downloads/) or install it from the Microsoft Store on Windows. Either method works, the Microsoft Store version installs to a user-local path and does not require administrator privileges.

### Virtual Environments

For a single-user local tool like this, a virtual environment is optional. If you prefer to isolate dependencies:

```bash
python -m venv venv

# Linux/macOS
source venv/bin/activate

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1

# Windows (cmd)
.\venv\Scripts\activate.bat
```

If you skip the virtual environment, `pip install` will install packages to your user site-packages directory. This is fine for a project with only four dependencies that are unlikely to conflict with anything else on your system.

### Containerization

A project like this is a poor candidate for containerization. The pipeline depends on two localhost services, LM Studio and Anki, that run as desktop GUI applications on the host machine. Putting the Python code inside a Docker container would require exposing those host ports into the container, mounting volumes for audio files, and dealing with cross-platform path differences.

The reproducibility problem that containers solve is better addressed here by pinning dependency versions in `requirements.txt` if needed. The project has four direct dependencies and all of them are stable, well-maintained packages.

## Dependencies

### requirements.txt

```
jamdict
jamdict-data
edge-tts
requests
```

These are the four direct dependencies:

| Package | Purpose | Installs |
|---------|---------|----------|
| `jamdict` | Python interface to JMdict and KANJIDIC2 Japanese dictionaries | Query API + SQLite database driver |
| `jamdict-data` | Pre-packaged dictionary database (~54 MB compressed) | SQLite database file containing JMdict + KANJIDIC2 |
| `edge-tts` | Text-to-speech via Microsoft Edge's TTS service | Async TTS client with voice selection |
| `requests` | HTTP client | Used for LM Studio and AnkiConnect API calls |

### Installation

```bash
pip install -r requirements.txt
```

#### The `jamdict-data` Problem on Windows

`jamdict-data` has a known installation issue on Windows. The package bundles a compressed SQLite database (`jamdict.db.xz`) that gets decompressed during installation. On Windows, the build process sometimes fails with `WinError 32` ("The process cannot access the file because it is being used by another process") because the installer tries to delete the `.xz` file while it is still memory-mapped.

If the install fails, try these steps in order:

**1. Install `wheel` first, then retry:**

```bash
pip install wheel
pip install -r requirements.txt
```

The `wheel` package provides an alternative build path that sometimes avoids the file lock.

**2. If it still fails, install `jamdict-data` separately with `setup.py`:**

```bash
pip install jamdict edge-tts requests
pip download jamdict-data --no-binary :all: -d /tmp/jd
cd /tmp/jd
tar xzf jamdict_data-1.5.tar.gz
cd jamdict_data-1.5
python setup.py install --user
```

**3. If the database file is installed but not decompressed, decompress it manually:**

```python
import lzma, shutil, jamdict_data, os

xz_path = os.path.join(os.path.dirname(jamdict_data.__file__), "jamdict.db.xz")
db_path = xz_path.replace(".xz", "")

with lzma.open(xz_path, "rb") as f_in, open(db_path, "wb") as f_out:
    shutil.copyfileobj(f_in, f_out)
```

Run this as a one-off script or in a Python REPL. It reads the compressed database and writes the decompressed version alongside it.

### Verifying the Install

After installation, verify that all packages import correctly:

```bash
python -c "from jamdict import Jamdict; print('jamdict OK')"
python -c "import edge_tts; print('edge-tts OK')"
python -c "import requests; print('requests OK')"
```

The `jamdict` import will take a moment on first run as it locates the database file.

## LM Studio

LM Studio is a desktop application that runs large language models locally and exposes them through an OpenAI-compatible HTTP API. The `llm.py` module sends requests to this API. It's not required to use LMStudio, as any OpenAI-compatible LLM-service will work, but this tutorial will assume LMStudio is used, as it provides an easy overview to see what model you can and cannot run, as well as GPU off-loading and easy access to quantizations.

### Installation

Download LM Studio from [lmstudio.ai](https://lmstudio.ai). It is available for Windows, macOS, and Linux. Install it like any desktop application.

### Loading a Model

After launching LM Studio, you need to download and load a model. From the home screen:

1. Use the search bar to find a model. For Japanese language tasks, instruction-tuned models in the 7B–13B parameter range work well. Some options:
   - `Qwen2.5-7B-Instruct` — strong multilingual performance, good Japanese
   - `Mistral-7B-Instruct` — reliable general-purpose instruction following
   - `Llama-3.1-8B-Instruct` — solid baseline with good structured output

2. Select a quantization level. Quantization compresses the model to use less memory at the cost of some quality. Common levels:
   - `Q4_K_M` - good balance of quality and memory usage (~4–5 GB for a 7B model)
   - `Q5_K_M` - slightly better quality, slightly more memory
   - `Q8_0` - near-original quality, ~2x the memory of Q4

   If your GPU has 8 GB of VRAM, a 7B model at Q4_K_M will fit comfortably. If you have 16 GB or more, you can run larger models or higher quantization levels.

3. Click **Download** and wait for the download to complete.

### Starting the Local Server

Once a model is loaded:

1. Navigate to the **Local Server** tab (in the left sidebar).
2. Select the model you downloaded.
3. Click **Start Server**.

The server starts on `http://localhost:1234` by default. You can verify it is running:

```bash
curl http://localhost:1234/v1/models
```

Or with Python:

```python
import requests
r = requests.get("http://localhost:1234/v1/models")
print(r.json())
```

This should return a JSON response listing the loaded model. The exact model name does not matter, the `config.py` file uses `"local-model"` as a placeholder, and LM Studio routes to whatever model is currently loaded regardless of the name in the request.

### Configuration

The relevant config values in `config.py`:

```python
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_STUDIO_MODEL = "local-model"
```

`LM_STUDIO_URL` points to the chat completions endpoint, which follows the OpenAI API format. `LM_STUDIO_MODEL` is sent in the request body, LM Studio requires the field to be present but ignores its value, always routing to the loaded model.

If you changed the port in LM Studio's server settings, update `LM_STUDIO_URL` accordingly.

## Anki and AnkiConnect

### Installing Anki

Download Anki from [apps.ankiweb.net](https://apps.ankiweb.net). Install and launch it. If this is a fresh install, you will have a single default deck.

### Installing AnkiConnect

[AnkiConnect](https://foosoft.net/projects/anki-connect/) is a third-party Anki add-on that exposes a JSON-over-HTTP API on `localhost:8765`. Our `anki_connect.py` module uses this API to create decks, store media files, and add notes.

To install:

1. In Anki, go to **Tools > Add-ons > Get Add-ons...**
2. Enter the add-on code: `2055492159`
3. Click **OK** and restart Anki.

After restarting, AnkiConnect runs silently in the background whenever Anki is open. Verify it is running:

```bash
curl http://localhost:8765 -X POST -d "{\"action\": \"version\", \"version\": 6}"
```

Or with Python:

```python
import requests
r = requests.post("http://localhost:8765", json={"action": "version", "version": 6})
print(r.json())  # {"result": 6, "error": null}
```

### Note Types and Deck Configuration

This tool uses the `Basic` note type, which ships with every Anki installation. It has two fields: `Front` and `Back`. The flashcard module writes HTML into these fields, including `[sound:filename.mp3]` tags that Anki renders as audio players.

The deck name is set in `config.py`:

```python
ANKI_DECK_NAME = "Japanese"
ANKI_NOTE_TYPE = "Basic"
```

The tool creates the deck automatically if it does not exist (via AnkiConnect's `createDeck` action), so there is no manual deck setup required. If you want to use a different deck name or note type, change these values before running the tool.

### AnkiConnect Permissions

By default, AnkiConnect accepts requests from any origin on localhost. If you have modified AnkiConnect's configuration (Tools > Add-ons > AnkiConnect > Config), ensure that `webCorsOriginList` includes `*` or is not overly restrictive:

```json
{
    "apiKey": null,
    "apiLogPath": null,
    "webBindAddress": "127.0.0.1",
    "webBindPort": 8765,
    "webCorsOriginList": ["*"]
}
```

If you have set an `apiKey`, you will need to modify `anki_connect.py` to include it in requests. The default configuration (no API key) is assumed throughout this tutorial.

## config.py

With all services installed and verified, the full configuration file:

```python
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_STUDIO_MODEL = "local-model"
ANKI_CONNECT_URL = "http://localhost:8765"
ANKI_DECK_NAME = "Japanese"
ANKI_NOTE_TYPE = "Basic"
AUDIO_DIR = "audio/"
```

Six constants, all pointing to local resources. Modules that communicate with external services (`llm.py`, `tts.py`, `anki_connect.py`) import this file to resolve endpoints and paths. There is no environment variable parsing, no `.env` file loading, and no runtime configuration. If you need to change a value, you edit this file and re-run the tool.

`AUDIO_DIR` is a relative path. Generated `.mp3` files are written here during the TTS stage, then read back during the AnkiConnect stage (to base64-encode and upload them to Anki's media folder). The directory is created automatically if it does not exist.
