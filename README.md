# Screen capture + real-time OCR

Capture a specific window (e.g. Chrome), save screenshot frames with timestamps, and extract text via OCR in real time. Also supports continuous video-like capture from a rectangular region (by coordinates) with MP4 output.

## Prerequisites

- **Python 3.9+**
- **Tesseract OCR** — required for text extraction.
  - Install: [Tesseract at UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) (Windows).
  - Either add the install folder to your PATH, or set `TESSERACT_CMD` in `.env` to the full path to `tesseract.exe`, e.g. `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`.

## Quick start (Windows)

Double-click **`run.bat`**, or from a terminal in `d:\detector`:

```powershell
run.bat
```

That is all that is needed. `run.bat` creates `.env` from `.env.example` if it is
missing, creates `.venv` and installs dependencies if they are missing, then
launches the GUI (`app.py`).

`run.ps1` does the same work and is what `run.bat` calls. Running it directly
fails on a default Windows install with *"running scripts is disabled on this
system"*, because the execution policy is `Restricted` out of the box. Either use
`run.bat` (it passes `-ExecutionPolicy Bypass` for that one process and changes
nothing system-wide), or allow local scripts for your user account once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

If you already have a `.venv` from before a dependency was added to
`requirements.txt`, `run.bat` will not repair it — it only installs when `.venv`
is absent. Refresh it with:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Before running detection, set `OPENAI_API_KEY` in `.env` (used for multiplier
prediction) and make sure Tesseract is installed, per Prerequisites above.

On macOS/Linux the equivalent launcher is `./run.sh`.

## Manual setup

Use this if you would rather set things up yourself instead of using `run.bat`.


1. **Create and activate virtual environment**

   ```powershell
   cd d:\detector
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. **Install dependencies**

   ```powershell
   pip install -r requirements.txt
   ```

3. **Environment (optional)**

   Copy `.env.example` to `.env` and adjust:

   ```powershell
   copy .env.example .env
   ```

   Variables: `CAPTURE_INTERVAL_SEC`, `OUTPUT_DIR`, `FRAMES_DIR`, `TEXTS_DIR`, `CAPTURE_FPS`.

## Usage

### Window capture (with OCR)

- **List windows** (to find the right title for capture):

  ```powershell
  python main.py --list-windows
  ```

- **Capture a window** by title substring (e.g. "Chrome"):

  ```powershell
  python main.py --window "Chrome"
  ```

- **Override interval** (seconds between captures):

  ```powershell
  python main.py --window "Chrome" --interval 2
  ```

Frames are saved under the configured frames directory with filenames like `frame_2025-03-07_14-30-00.png`. OCR text is saved in the texts directory with matching timestamps.

### Region capture (continuous frames / video)

- **Capture a region** by coordinates (x, y, width, height), save as MP4:

  ```powershell
  python main.py --region 100,100,800,600 --fps 20 --video output.mp4
  ```

- **Capture a region**, save as individual frames:

  ```powershell
  python main.py --region 100,100,800,600 --fps 15
  ```

- **GUI** (region picker + capture):

  ```powershell
  python app.py
  ```

  Use "Select region" to drag a rectangle on screen, set FPS and output path, then "Start capture". Press Stop to end (or close the app).
