"""
gemini_scanner.py — Google Gemini-powered Sudoku image scanner

Sends the captured/uploaded photo directly to Google's Gemini multimodal
model and asks it to read off the 9x9 grid of digits (0 = empty cell).
Because Gemini "looks at" the whole picture the way a person would, this
generalizes to any Sudoku photo, screenshot, or printed puzzle — unlike a
template-specific OpenCV pipeline tuned for one app's exact colors/fonts.

Configuration (environment variables):
    GEMINI_API_KEY   — required. Get a free key at https://aistudio.google.com/apikey
    GEMINI_MODEL     — optional. Defaults to "gemini-flash-latest"
                        (Google's auto-updated alias for their current
                        fast multimodal model).

Response contract (matches the legacy OpenCV scanner's shape, so the
existing frontend review modal works unchanged):
    {
        success: bool,
        grid: int[9][9] | None,      # 0 = empty, 1-9 = digit
        confidence: float[9][9] | None,
        scan_id: str | None,
        message: str
    }
"""

import os
import json
import re
from urllib import response
import uuid
import base64
import shutil
import tempfile
from pathlib import Path

import requests
import time

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
REQUEST_TIMEOUT_SECONDS = 30

# Where we stash the source image + detected grid for the review/confirm flow.
# IMPORTANT: this must live OUTSIDE the project folder. Flask's debug-mode
# auto-reloader watches the project directory for changes; writing new files
# into a subfolder of the project (e.g. ./scan_cache) during a request makes
# it think source code changed, triggers a server restart, and kills the
# in-flight request — which shows up in the browser as "failed to connect".
SCAN_CACHE_DIR = Path(tempfile.gettempdir()) / 'sudoku_scan_cache'

PROMPT = """You are looking at a photo or screenshot of an unsolved Sudoku puzzle.
Read the 9x9 grid exactly as printed/drawn, row by row, left to right, top to bottom.

Rules:
- Respond with ONLY a single JSON object. No markdown code fences, no commentary, no explanation.
- "grid": a 9x9 array of arrays of integers. Use 0 for an empty cell, and 1-9 for a filled cell's printed digit.
- "confidence": a 9x9 array of arrays of numbers between 0 and 1 — your confidence that each cell (including empty ones) was read correctly.
- Read each digit exactly as it visually appears, even if it would make the puzzle invalid or unsolvable. Do not "correct" digits to make the puzzle work out — just report what you see.
- Ignore borders, gridlines, watermarks, logos, and UI chrome outside the 9x9 board.
- If you cannot locate a 9x9 sudoku grid anywhere in the image, respond with exactly: {"grid": null, "confidence": null, "error": "<short reason>"}

Respond with JSON only, matching this exact shape:
{"grid": [[0,0,0,0,0,0,0,0,0], ... 9 rows ...], "confidence": [[0.9,0.9,...], ... 9 rows ...]}
"""


class GeminiScannerError(Exception):
    """Raised internally when the Gemini response can't be parsed."""
    pass


class GeminiSudokuScanner:
    """Scans Sudoku puzzle images using the Google Gemini API."""

    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = (os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL)

    @property
    def is_configured(self):
        """True if a Gemini API key has been provided via environment variable."""
        return bool(self.api_key)

    # ── Public API ───────────────────────────────────────────────────────────

    def scan(self, image_bytes, mime_type="image/jpeg"):
        """
        Scan a Sudoku puzzle photo using Gemini's vision understanding.

        Args:
            image_bytes: Raw image bytes (JPEG/PNG/WebP/etc.)
            mime_type: MIME type of the image (e.g. 'image/jpeg')

        Returns:
            dict — see module docstring for the response shape.
        """
        if not self.is_configured:
            return self._fail(
                'Gemini API key not configured. Set the GEMINI_API_KEY '
                'environment variable (get a free key at '
                'https://aistudio.google.com/apikey) to enable Google AI image scanning.'
            )

        # try:
        #     response = requests.post(
        #         GEMINI_API_URL.format(model=self.model),
        #         headers={
        #             "Content-Type": "application/json",
        #             "x-goog-api-key": self.api_key,
        #         },
        #         json=self._build_payload(image_bytes, mime_type),
        #         timeout=REQUEST_TIMEOUT_SECONDS,
        #     )
        # except requests.RequestException as e:
        #     return self._fail(f'Could not reach the Gemini API: {e}')

        # if response.status_code != 200:
        #    print("Status Code:", response.status_code)
        #    print(response.text)
        #    return self._fail(f'Gemini API error ({response.status_code})')
        response = None

        for attempt in range(3):
            try:
                response = requests.post(
                    GEMINI_API_URL.format(model=self.model),
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.api_key,
                    },
                    json=self._build_payload(image_bytes, mime_type),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )

                if response.status_code == 200:
                    break

                if response.status_code == 503 and attempt < 2:
                    print(f"Gemini busy. Retrying... ({attempt + 1}/3)")
                    time.sleep(2)
                    continue

                break

            except requests.RequestException as e:
                if attempt < 2:
                    print(f"Network error. Retrying... ({attempt + 1}/3)")
                    time.sleep(2)
                    continue
                return self._fail(f'Could not reach the Gemini API: {e}')

        if response.status_code != 200:
            return self._fail(f'Gemini API error ({response.status_code}): {self._short_error(response)}')
        try:
            parsed = self._extract_json(response.json())
        except (GeminiScannerError, ValueError, KeyError, IndexError) as e:
            return self._fail(f'Could not parse Gemini response: {e}')

        print(f'[gemini_scanner] model={self.model} raw_parsed={json.dumps(parsed)[:1500]}')

        if parsed.get('grid') is None:
            return self._fail(parsed.get('error') or 'Gemini could not find a 9x9 Sudoku grid in this image.')

        try:
            grid, confidence = self._sanitize(parsed)
        except GeminiScannerError as e:
            return self._fail(f'Gemini returned a malformed grid: {e}')

        scan_id = str(uuid.uuid4())[:8]
        self._cache_scan(scan_id, image_bytes, mime_type, grid)

        return {
            'success': True,
            'engine': 'gemini',
            'grid': grid,
            'confidence': confidence,
            'scan_id': scan_id,
            'message': 'Scan complete (via Google Gemini). Please verify the detected digits.'
        }

    # ── Internals ────────────────────────────────────────────────────────────

    def _fail(self, message):
        return {
            'success': False,
            'engine': None,
            'grid': None,
            'confidence': None,
            'scan_id': None,
            'message': message
        }

    def _build_payload(self, image_bytes, mime_type):
        b64 = base64.b64encode(image_bytes).decode('ascii')
        return {
            "contents": [{
                "parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": mime_type, "data": b64}}
                ]
            }],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0,
            }
        }

    def _short_error(self, response):
        try:
            data = response.json()
            return data.get('error', {}).get('message', response.text[:200])
        except Exception:
            return response.text[:200]

    def _extract_json(self, response_json):
        candidates = response_json.get('candidates') or []
        if not candidates:
            feedback = response_json.get('promptFeedback', {})
            reason = feedback.get('blockReason')
            raise GeminiScannerError(reason or 'empty response from model')

        parts = candidates[0].get('content', {}).get('parts', [])
        text = ''.join(p.get('text', '') for p in parts).strip()
        if not text:
            raise GeminiScannerError('model returned no text')

        # Strip markdown code fences, just in case the model adds them anyway.
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())

        return json.loads(text)

    def _sanitize(self, parsed):
        """Coerce the model's JSON into a strict 9x9 int grid + confidence grid."""
        raw_grid = parsed.get('grid')
        raw_conf = parsed.get('confidence')

        if not isinstance(raw_grid, list) or len(raw_grid) != 9:
            raise GeminiScannerError('grid is not a 9x9 array')

        grid = [[0] * 9 for _ in range(9)]
        confidence = [[0.9] * 9 for _ in range(9)]

        for r in range(9):
            row = raw_grid[r]
            if not isinstance(row, list) or len(row) != 9:
                raise GeminiScannerError(f'row {r + 1} is not length 9')
            for c in range(9):
                try:
                    v = int(row[c])
                except (TypeError, ValueError):
                    v = 0
                grid[r][c] = v if 0 <= v <= 9 else 0

        if isinstance(raw_conf, list) and len(raw_conf) == 9:
            for r in range(9):
                row = raw_conf[r]
                if isinstance(row, list) and len(row) == 9:
                    for c in range(9):
                        try:
                            v = float(row[c])
                        except (TypeError, ValueError):
                            v = 0.9
                        confidence[r][c] = max(0.0, min(1.0, v))

        return grid, confidence

    def _cache_scan(self, scan_id, image_bytes, mime_type, grid):
        """Cache the source image + detected grid for the review/confirm flow."""
        try:
            cache_dir = SCAN_CACHE_DIR / scan_id
            cache_dir.mkdir(parents=True, exist_ok=True)
            ext = '.png' if 'png' in mime_type else '.jpg'
            with open(cache_dir / f'source{ext}', 'wb') as f:
                f.write(image_bytes)
            with open(cache_dir / 'grid.json', 'w') as f:
                json.dump({'engine': 'gemini', 'grid': grid}, f)
        except OSError:
            pass  # Caching is best-effort; the scan result is still valid without it.

    def cleanup_scan_cache(self, scan_id):
        """Remove a cached scan (called once the user confirms/discards it)."""
        cache_dir = SCAN_CACHE_DIR / scan_id
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
