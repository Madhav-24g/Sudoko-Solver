# Sudoku Scanner & Solver

A professional, high-performance Sudoku Solver & Scanner application. It features a responsive web interface (HTML, CSS, JS) powered by a Python Flask backend utilizing OpenCV for highly accurate, template-optimized grid and digit extraction.

## Features

- **Google Gemini Image Scanner** — Send any photo or screenshot of a Sudoku puzzle and Gemini's multimodal vision reads off the full 9×9 grid directly, generalizing far beyond one specific app's look. Falls back automatically to a local OpenCV template-matching scanner if no Gemini API key is configured or the API is unreachable.
- **Mathematically Rigorous Solver** — Python Flask backend utilizing Constraint Propagation and MRV Backtracking to solve any valid puzzle.
- **Returns a Solution Either Way** — If a puzzle has a unique solution, that's what you get. If it has multiple valid solutions, the solver still hands back one of them (clearly flagged as non-unique) instead of refusing.
- **Scan Verification & Review Modal** — Allows visual review of scanned inputs, highlighting low-confidence cells, and allows corrections before confirmation.
- **Continuous Learning (fallback mode)** — When using the local OpenCV fallback scanner, corrected cell inputs are fed back to the server to save template images, boosting recognition accuracy dynamically.
- **Mobile Support & Digit Pad** — Desktop inputs work seamlessly on mobile (Android/iOS) with a responsive touch digit keypad, camera capture, and file upload options.
- **Real-Time Validation** — Instantly highlights grid cell conflicts and constraints as you type.
- **Strict Boundary Navigation** — Clean arrow key navigation that stops at grid borders without unexpected jumps.

---

## Configuring the Google Gemini Scanner

1. Get a free API key at **https://aistudio.google.com/apikey**.
2. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
3. Open `.env` and set:
   ```
   GEMINI_API_KEY=your-key-here
   ```
4. Restart `python app.py`. The startup banner will confirm `Gemini scanner: ACTIVE`.

If you skip this step, image scanning still works — it just uses the older, less general local OpenCV scanner as a fallback, and the server log/UI message will say so.

---

## Installation & Setup

Ensure you have Python 3.8+ installed on your computer.

### 1. Install Dependencies
Navigate to the project folder and run:
```bash
pip install -r requirements.txt
```

### 2. Run the Server
Start the Flask application:
```bash
python app.py
```

By default, the server will bind to port `5000` and list both local and network access links:
- **Local:** `http://localhost:5000`
- **Network:** `http://<your-computer-ip>:5000`

---

## Accessing from Mobile Devices (Same Wi-Fi Network)

To run the camera scanner on your iPhone or Android phone, connect it to the **same Wi-Fi network** as your computer:

1. Look up your computer's local IP address (e.g., `192.168.1.45`). The startup logs of `app.py` will print this automatically.
2. Open your mobile browser and navigate to `http://<your-computer-ip>:5000`.
3. Tap **Scan Camera** or **Scan Image** to scan the template directly from your phone.
4. *Note on HTTPS*: Standard mobile browsers restrict camera access (getUserMedia) to secure origins (HTTPS) or `localhost`. If your mobile browser blocks the camera stream on local Wi-Fi, use **Scan Image** instead, which lets you take a photo with your phone's native camera or upload an existing image. This is highly recommended as native cameras deliver much better resolution and focusing!

---

## Folder Structure

```
sudoku-solver/
├── app.py              — Flask Server (API routing & static hosting)
├── gemini_scanner.py   — Google Gemini-powered image scanner (primary)
├── scanner.py          — OpenCV image processing & custom OCR templates (fallback)
├── solver_engine.py    — Mathematically rigorous Python solver
├── requirements.txt    — Python package requirements
├── .env.example        — Copy to .env and add your GEMINI_API_KEY
├── index.html          — App dashboard (HTML)
├── style.css           — Standard styles (Light/Dark themes)
├── app.js              — Frontend event handling & UI states
├── solver.js           — Client-side integration & local fallback
└── digit_templates/    — Saved digit images for the OpenCV fallback scanner
```

---

## How It Works

1. **Image Upload/Capture**: The frontend sends the photo to `/api/scan`.
2. **Gemini Vision Read**: If `GEMINI_API_KEY` is set, the image is sent to Google's Gemini API with a prompt asking it to transcribe the 9×9 grid (0 for empty cells) as JSON. This works on printed puzzles, screenshots, or photos from any app/book, not just one fixed template.
3. **OpenCV Fallback**: If Gemini isn't configured or the request fails, the app falls back to a local pipeline — adaptive thresholding finds the grid, a perspective transform squares it up, each cell is classified filled/empty, and digits are matched against saved templates.
4. **Review & Solve**: The detected grid is shown for review/correction, then handed to the constraint-propagation + backtracking solver. If the puzzle has a unique solution, that's returned; if it has multiple valid solutions, the solver still returns one of them rather than refusing.
5. **Local Fallback**: If the backend becomes unreachable, the frontend automatically falls back to the client-side JavaScript solver, keeping the app functional offline.
