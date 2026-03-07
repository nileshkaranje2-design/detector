# Screen capture + real-time OCR

Capture a specific window (e.g. Chrome), save screenshot frames with timestamps, and extract text via OCR in real time. Also supports continuous video-like capture from a rectangular region (by coordinates) with MP4 output.

## Prerequisites

- **Python 3.9+**
- **Tesseract OCR** — required for text extraction.
  - Install: [Tesseract at UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) (Windows).
  - Either add the install folder to your PATH, or set `TESSERACT_CMD` in `.env` to the full path to `tesseract.exe`, e.g. `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`.

## Setup

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
