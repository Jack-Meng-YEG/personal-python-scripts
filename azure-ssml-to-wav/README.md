# Azure SSML to WAV Pipeline

This script takes a large SSML file, automatically splits it into smaller parts,
synthesizes each part with **Azure Speech Service**, and then concatenates the
resulting WAV files into one final audio file (optionally also exporting MP3).

It is designed to work around common Azure limits such as:

- Maximum characters per request (e.g. around 3000 characters)
- Limits on the number of segments / `<voice>` elements per synthesis call

---

## Features

- Robust parsing of SSML:
  - Handles BOM, XML prolog (`<?xml ...?>`), and comments before `<speak>`
  - Safely extracts the `<speak> ... </speak>` root element
- Splits a large SSML file by `<voice>` blocks:
  - Each part contains at most **N** `<voice>` elements (default `48`)
  - Helps avoid Azure per-request character / segment limits
- Calls Azure Speech to synthesize each part as **24kHz 16-bit mono WAV**
- Concatenates all WAV parts into one final WAV file
- Optional MP3 export (via `pydub` + `ffmpeg`)
- Basic retry logic on network errors / timeouts

---

## Prerequisites

1. **Azure Speech resource**

   - Create a *Speech service* resource in Azure Portal or Speech Studio.
   - Note your:
     - **Key** (subscription key)
     - **Region** (e.g. `canadacentral`, `eastus`, etc.)

2. **Python**

   - Python 3.8+ is recommended.

3. **Python packages**

   ```bash
   pip install azure-cognitiveservices-speech
   # Optional (for MP3 export):
   pip install pydub
   ```

4. **ffmpeg (only if you want MP3 output)**

   - Install `ffmpeg` and make sure it is on your `PATH`, for example:
     - **Ubuntu / WSL:**
       ```bash
       sudo apt update
       sudo apt install ffmpeg
       ```
     - **Windows (choco):**
       ```powershell
       choco install ffmpeg
       ```
   - By default the script assumes `ffmpeg` is available as `ffmpeg`.
     - If not, you can set `FFMPEG_PATH` to the full path of the ffmpeg binary:
       ```bash
       export FFMPEG_PATH="/usr/bin/ffmpeg"
       ```

---

## Environment Variables

Set your Azure Speech key and region **before** running the script:

```bash
# Linux / macOS / WSL
export SPEECH_KEY="YOUR_AZURE_SPEECH_KEY"
export SPEECH_REGION="YOUR_REGION"   # e.g. canadacentral, eastus

# Windows PowerShell
$env:SPEECH_KEY = "YOUR_AZURE_SPEECH_KEY"
$env:SPEECH_REGION = "YOUR_REGION"
```

Alternatively, you can also use:

- `AZURE_SPEECH_KEY`
- `AZURE_SPEECH_REGION`

The script checks `SPEECH_KEY` / `AZURE_SPEECH_KEY` and `SPEECH_REGION` / `AZURE_SPEECH_REGION`
(in that order) and defaults to `canadacentral` if no region is set.

---

## Basic Usage

Assume your script is named **`azure_ssml_to_wav.py`** and is in the current directory.

```bash
python3 azure_ssml_to_wav.py input.ssml --out out_dir --to-mp3
```

- `input.ssml` – your large SSML file.
- `--out out_dir` – output directory (default: `out`).
- `--to-mp3` – additionally export a final MP3 file (requires `pydub` + `ffmpeg`).

After running, the directory structure looks like:

```
out_dir/
  parts/
    input.part01.ssml
    input.part02.ssml
    ...
  wavs/
    input.part01.wav
    input.part02.wav
    ...
  input.final.wav
  input.final.mp3        # if --to-mp3 was used
```

---

## Command-line Arguments

```bash
python3 azure_ssml_to_wav.py SSML_FILE [options]
```

**Positional:**

- `SSML_FILE`  
  Path to the original SSML file.

**Options:**

- `--out OUT_DIR`  
  Output directory (default: `out`).

- `--max-voices N`  
  Maximum number of `<voice>` elements per split part (default: `48`).  
  Lower this value if you still hit Azure limits (e.g. 3000 characters per request).

- `--no-split`  
  Do not split the main SSML.  
  The script will instead look for pre-split files matching `parts/*.part*.ssml`.

- `--to-mp3`  
  After concatenating WAV parts into `*.final.wav`, also export `*.final.mp3`
  (requires `pydub` and `ffmpeg`).

---

## How the Splitting Works (Limits & Quotas)

Azure Speech has both:

- A **per-request character limit** (e.g. ~3000 characters), and
- Limits on the number of segments / voice elements per request.

This script uses a simple but practical strategy:

1. It parses your SSML and finds the outer `<speak> ... </speak>` element.
2. Inside, it searches for `<voice> ... </voice>` blocks.
3. It groups these blocks so that each group contains at most `max_voices`
   `<voice>` elements (default: `48`).
4. Each group is written to a separate `*.partXX.ssml` file and sent as one
   synthesis request.

This means:

- You avoid sending a single huge SSML document that exceeds Azure’s
  character limit.
- You reduce the chance of hitting limits like “50 segments per request”.
- If you still hit a character limit, reduce `--max-voices` (e.g. `--max-voices 24`)
  so each part becomes smaller.

---

## Examples

### 1. Default split + WAV

```bash
python3 azure_ssml_to_wav.py lesson01.ssml
```

- Splits `lesson01.ssml` by `<voice>` (max 48 per part).
- Saves parts in `out/parts`.
- Synthesizes each part to `out/wavs/*.wav`.
- Concatenates into `out/lesson01.final.wav`.

### 2. Split + WAV + MP3

```bash
python3 azure_ssml_to_wav.py lesson01.ssml --out audio --to-mp3
```

- Same as above, but outputs to `audio/` and also creates `audio/lesson01.final.mp3`.

### 3. Use a smaller `max-voices` value

```bash
python3 azure_ssml_to_wav.py long_book.ssml --max-voices 24
```

### 4. Re-use manually edited parts (`--no-split`)

If you have already generated and manually corrected `*.partXX.ssml` files
under `out/parts`, you can skip the split step:

```bash
python3 azure_ssml_to_wav.py long_book.ssml --out out --no-split
```

The script will:

- Read all `out/parts/*.part*.ssml`,
- Synthesize them,
- Concatenate the resulting WAV files.

---

## Running from Anywhere (PATH tips)

- Place `azure_ssml_to_wav.py` in a directory of your choice.
- From a terminal, `cd` into that directory, then run:

  ```bash
  python3 azure_ssml_to_wav.py your_file.ssml ...
  ```

- If you want to call it from anywhere, you can:
  - Add the directory to your `PATH`, or
  - Create a small shell script / batch file that calls:

    ```bash
    python3 /full/path/to/azure_ssml_to_wav.py "$@"
    ```

---

## Troubleshooting

- **Missing SPEECH_KEY / region**

  Make sure you set `SPEECH_KEY` (or `AZURE_SPEECH_KEY`) and
  `SPEECH_REGION` (or `AZURE_SPEECH_REGION`) before running.

- **Connection / timeout errors**

  The script has basic retry logic.  
  If failures persist, check your network and Azure region.

- **MP3 not generated**

  Ensure `pydub` is installed and `ffmpeg` is available in your `PATH`
  or via `FFMPEG_PATH`.

---
