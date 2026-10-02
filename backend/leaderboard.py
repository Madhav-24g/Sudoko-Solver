"""
backend/leaderboard.py — Persistent Leaderboard Engine

Stores top Sudoku Arena scores in a JSON file inside backend/data/.
Thread-safe: uses a file lock via a .lock sentinel to prevent corruption.

Data schema:
  {
    "easy":   [ { "name": str, "score": int, "time": int, "date": str }, ... ],
    "medium": [ ... ],
    "hard":   [ ... ],
    "expert": [ ... ]
  }

At most MAX_PER_DIFFICULTY entries are kept per difficulty, sorted by score desc.
"""

import json
import os
import time
from pathlib import Path

# Storage directory — inside backend/ so it travels with the rest of backend code
DATA_DIR = Path(__file__).parent / 'data'
LEADERBOARD_FILE = DATA_DIR / 'leaderboard.json'
LOCK_FILE = DATA_DIR / 'leaderboard.lock'

MAX_PER_DIFFICULTY = 20
DIFFICULTIES = ('easy', 'medium', 'hard', 'expert')


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _acquire_lock(timeout: float = 3.0) -> bool:
    """Primitive file-based lock. Returns True if lock acquired."""
    _ensure_data_dir()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # Exclusive create — fails if lock already exists
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.05)
    return False


def _release_lock():
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _load_raw() -> dict:
    """Load leaderboard from disk. Returns empty structure on any error."""
    empty = {d: [] for d in DIFFICULTIES}
    try:
        if LEADERBOARD_FILE.exists():
            with open(LEADERBOARD_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Validate structure — rebuild if keys are missing
            for d in DIFFICULTIES:
                if d not in data or not isinstance(data[d], list):
                    data[d] = []
            return data
    except Exception:
        pass
    return empty


def _save_raw(data: dict):
    """Write leaderboard atomically: write to temp file then rename."""
    _ensure_data_dir()
    tmp = LEADERBOARD_FILE.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(LEADERBOARD_FILE)


def get_leaderboard(difficulty: str = None) -> dict:
    """
    Return leaderboard data.
    If difficulty is specified, returns just that difficulty's list.
    Otherwise returns all difficulties.
    """
    data = _load_raw()
    if difficulty and difficulty in DIFFICULTIES:
        return {difficulty: data[difficulty]}
    return data


def add_score(name: str, difficulty: str, score: int, time_seconds: int, date: str) -> dict:
    """
    Add a new score entry. Returns the updated difficulty leaderboard list.

    Args:
        name:         Player name (max 20 chars, sanitized)
        difficulty:   One of 'easy', 'medium', 'hard', 'expert'
        score:        Integer score value
        time_seconds: Completion time in seconds
        date:         ISO date string (client-side)

    Returns:
        {'rank': int, 'entries': list, 'is_top': bool}
    """
    if difficulty not in DIFFICULTIES:
        raise ValueError(f'Invalid difficulty: {difficulty!r}')

    # Sanitize inputs
    name = str(name).strip()[:20] or 'Anonymous'
    score = max(0, int(score))
    time_seconds = max(0, int(time_seconds))
    date = str(date).strip()[:20]

    acquired = _acquire_lock()
    try:
        data = _load_raw()
        entries = data[difficulty]

        new_entry = {
            'name': name,
            'score': score,
            'time': time_seconds,
            'date': date,
        }

        entries.append(new_entry)

        # Sort by score descending, then by time ascending (lower time = better on tie)
        entries.sort(key=lambda e: (-e['score'], e['time']))

        # Keep only top MAX_PER_DIFFICULTY
        data[difficulty] = entries[:MAX_PER_DIFFICULTY]

        if acquired:
            _save_raw(data)

        # Find the rank of the newly added entry (0-indexed -> 1-indexed)
        rank = next(
            (i + 1 for i, e in enumerate(data[difficulty])
             if e['name'] == name and e['score'] == score and e['time'] == time_seconds),
            None
        )
        is_top = rank is not None and rank <= 10

        return {
            'rank': rank,
            'entries': data[difficulty],
            'is_top': is_top,
        }

    finally:
        if acquired:
            _release_lock()


def clear_leaderboard(difficulty: str = None):
    """Dev/admin: clear one or all difficulties. Not exposed via public API."""
    acquired = _acquire_lock()
    try:
        data = _load_raw()
        if difficulty and difficulty in DIFFICULTIES:
            data[difficulty] = []
        else:
            for d in DIFFICULTIES:
                data[d] = []
        if acquired:
            _save_raw(data)
    finally:
        if acquired:
            _release_lock()
