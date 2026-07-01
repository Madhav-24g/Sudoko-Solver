"""
app.py — Flask Server for Sudoku Scanner & Solver

Serves the frontend and provides REST API endpoints for:
- Image scanning (OpenCV-based digit recognition)
- Puzzle solving (constraint propagation + backtracking)
- Template learning (cache verified digits for improved accuracy)

Run: python app.py
Open: http://localhost:5000
LAN:  http://<your-ip>:5000 (for mobile testing)
"""

import os
import json
import time
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS

try:
    from dotenv import load_dotenv
    load_dotenv()  # Load GEMINI_API_KEY etc. from a local .env file, if present
except ImportError:
    pass  # python-dotenv is optional; env vars can also be set directly

from scanner import SudokuScanner
from gemini_scanner import GeminiSudokuScanner, SCAN_CACHE_DIR
from solver_engine import solve_puzzle, get_conflicts

import numpy as np
from flask.json.provider import DefaultJSONProvider


class NumpySafeJSONProvider(DefaultJSONProvider):
    """
    Safety net: the OpenCV fallback scanner can leak numpy scalar types
    (float32, int32, bool_, etc.) into response dicts. Flask's default
    JSON encoder can't serialize those and raises a TypeError deep inside
    jsonify(), which otherwise surfaces to users as an opaque 500 error.
    This coerces any numpy scalar to its native Python equivalent.
    """
    @staticmethod
    def default(obj):
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return DefaultJSONProvider.default(obj)


# ── Flask App Setup ──────────────────────────────────────────────────────────

app = Flask(__name__)
app.json = NumpySafeJSONProvider(app)
CORS(app)


def _detect_mime_type(image_bytes):
    """
    Detect the real image format from its bytes (ignoring whatever the
    browser/client claimed). Returns a mime_type string Gemini understands,
    or None if the bytes don't decode as a recognizable image at all.
    """
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(image_bytes)) as img:
            fmt = (img.format or '').upper()
    except Exception:
        return None

    return {
        'JPEG': 'image/jpeg',
        'PNG': 'image/png',
        'WEBP': 'image/webp',
        'HEIF': 'image/heif',
        'GIF': 'image/gif',
        'BMP': 'image/bmp',
    }.get(fmt)

# Primary scanner: Google Gemini (general-purpose, works on any Sudoku photo).
gemini_scanner = GeminiSudokuScanner()
# Fallback scanner: local OpenCV template matching, used only if Gemini isn't
# configured or is unreachable, so the app still works offline / without a key.
scanner = SudokuScanner()

# Allowed static file extensions (security: don't serve .py files)
ALLOWED_EXTENSIONS = {'.html', '.css', '.js', '.ico', '.png', '.jpg',
                      '.jpeg', '.svg', '.webp', '.gif', '.woff', '.woff2',
                      '.ttf', '.json', '.map'}

# Max upload size: 16MB
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024


# ── Static File Serving ──────────────────────────────────────────────────────

@app.route('/')
def serve_index():
    """Serve the main page."""
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    """Serve static files (HTML, CSS, JS, images) from project root."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ALLOWED_EXTENSIONS:
        return send_from_directory('.', path)
    abort(404)


# ── API: Scan Image ──────────────────────────────────────────────────────────

@app.route('/api/scan', methods=['POST'])
def api_scan():
    """
    Scan a Sudoku puzzle from an uploaded image.

    Uses Google's Gemini API to read the grid (works on any Sudoku photo
    or screenshot). If Gemini isn't configured or is unreachable, falls
    back to the local OpenCV template-matching scanner.

    Request: multipart/form-data with 'image' file
    Response: {
        success: bool,
        grid: int[9][9],
        confidence: float[9][9],
        scan_id: str,
        message: str
    }
    """
    if 'image' not in request.files:
        return jsonify({
            'success': False,
            'message': 'No image file provided. Send as multipart/form-data with field name "image".'
        }), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({
            'success': False,
            'message': 'Empty filename.'
        }), 400

    try:
        image_bytes = file.read()
        if len(image_bytes) == 0:
            return jsonify({
                'success': False,
                'message': 'Empty file.'
            }), 400

        # Don't trust the browser-reported MIME type — some browsers/devices
        # send generic or wrong values (e.g. application/octet-stream).
        # Detect the *actual* format from the bytes themselves so Gemini
        # gets accurate metadata about what it's decoding.
        mime_type = _detect_mime_type(image_bytes)
        if mime_type is None:
            return jsonify({
                'success': False,
                'message': (
                    "This file doesn't look like a valid image (couldn't be "
                    "decoded as JPEG/PNG/WEBP/etc.). Try re-saving or "
                    "re-exporting the screenshot and uploading again."
                )
            }), 400

        if gemini_scanner.is_configured:
            result = gemini_scanner.scan(image_bytes, mime_type)
            if result['success']:
                return jsonify(result)

            # Gemini failed (network/API/parse issue) — fall back to local OpenCV scanner.
            fallback = scanner.scan(image_bytes)
            if fallback.get('success'):
                fallback['message'] = (
                    f"Google Gemini scan failed ({result['message']}); "
                    f"used the local fallback scanner instead."
                )
            return jsonify(fallback)
        else:
            # No Gemini API key set — use the local OpenCV scanner directly.
            result = scanner.scan(image_bytes)
            note = ' [Set the GEMINI_API_KEY environment variable for more accurate Google AI scanning.]'
            result['message'] = (result.get('message') or '') + note
            return jsonify(result)

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Scan error: {str(e)}'
        }), 500


# ── API: Solve Puzzle ────────────────────────────────────────────────────────

@app.route('/api/solve', methods=['POST'])
def api_solve():
    """
    Solve a Sudoku puzzle.

    Request: JSON { grid: int[9][9] }
    Response: {
        success: bool,
        solution: int[9][9] | null,
        status: 'unique' | 'invalid' | 'unsolvable' | 'multiple',
        message: str,
        solve_time_ms: float
    }
    """
    data = request.get_json()
    if not data or 'grid' not in data:
        return jsonify({
            'success': False,
            'solution': None,
            'status': 'invalid',
            'message': 'Request must include a "grid" field with a 9x9 array.',
            'solve_time_ms': 0
        }), 400

    grid = data['grid']

    try:
        t0 = time.perf_counter()
        result = solve_puzzle(grid)
        t1 = time.perf_counter()

        result['solve_time_ms'] = round((t1 - t0) * 1000, 2)
        return jsonify(result)

    except Exception as e:
        return jsonify({
            'success': False,
            'solution': None,
            'status': 'invalid',
            'message': f'Solver error: {str(e)}',
            'solve_time_ms': 0
        }), 500


# ── API: Validate Puzzle ─────────────────────────────────────────────────────

@app.route('/api/validate', methods=['POST'])
def api_validate():
    """
    Validate a Sudoku grid and return conflict cells.

    Request: JSON { grid: int[9][9] }
    Response: {
        valid: bool,
        conflicts: [[row, col], ...],
        message: str
    }
    """
    data = request.get_json()
    if not data or 'grid' not in data:
        return jsonify({
            'valid': False,
            'conflicts': [],
            'message': 'Request must include a "grid" field.'
        }), 400

    grid = data['grid']
    conflicts = get_conflicts(grid)

    return jsonify({
        'valid': len(conflicts) == 0,
        'conflicts': conflicts,
        'message': '' if len(conflicts) == 0 else f'{len(conflicts)} conflicting cells found.'
    })


# ── API: Save Verified Templates ─────────────────────────────────────────────

@app.route('/api/confirm_scan', methods=['POST'])
def api_confirm_scan():
    """
    Confirm a scan result.

    If the scan came from the local OpenCV scanner, save the
    user-corrected digit crops as new templates (continuous learning).
    If it came from Gemini, there's nothing to train locally — just
    acknowledge and clear the cache.

    Request: JSON { scan_id: str, grid: int[9][9] }
    Response: { success: bool, message: str }
    """
    data = request.get_json()
    if not data or 'scan_id' not in data or 'grid' not in data:
        return jsonify({
            'success': False,
            'message': 'Request must include "scan_id" and "grid" fields.'
        }), 400

    scan_id = data['scan_id']
    grid = data['grid']

    cache_dir = SCAN_CACHE_DIR / scan_id
    engine = None
    meta_path = cache_dir / 'grid.json'
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                engine = json.load(f).get('engine')
        except (OSError, json.JSONDecodeError):
            engine = None

    try:
        if engine == 'gemini':
            gemini_scanner.cleanup_scan_cache(scan_id)
            return jsonify({
                'success': True,
                'message': 'Scan confirmed.'
            })

        # Legacy OpenCV path — save verified digit crops as templates.
        saved = scanner.save_verified_templates(scan_id, grid)
        if saved:
            return jsonify({
                'success': True,
                'message': 'Templates saved. Future scans will be more accurate.'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Could not find cached scan data. Templates not saved.'
            })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error saving templates: {str(e)}'
        })


# ── Health Check ─────────────────────────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check endpoint."""
    has_templates = len(scanner.digit_templates) > 0
    return jsonify({
        'status': 'ok',
        'gemini_configured': gemini_scanner.is_configured,
        'gemini_model': gemini_scanner.model if gemini_scanner.is_configured else None,
        'fallback_templates_loaded': has_templates,
        'fallback_template_digits': list(scanner.digit_templates.keys()) if has_templates else []
    })


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Clean up old scan caches on startup
    scanner.cleanup_old_caches()

    gemini_status = (
        f'ACTIVE (model: {gemini_scanner.model})' if gemini_scanner.is_configured
        else 'NOT CONFIGURED — set GEMINI_API_KEY (using local OpenCV fallback)'
    )

    print('\n+--------------------------------------------------+')
    print('|          Sudoku Scanner & Solver Server          |')
    print('+--------------------------------------------------+')
    print('|  Local:   http://localhost:5000                  |')
    print('|  Network: http://0.0.0.0:5000                    |')
    print(f'|  Gemini scanner: {gemini_status}')
    print('|                                                  |')
    print('|  For mobile access on the same Wi-Fi network,    |')
    print('|  use your computer\'s local IP address.           |')
    print('+--------------------------------------------------+\n')

    app.run(host='0.0.0.0', port=5000, debug=True)
