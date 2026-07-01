/**
 * app.js — Sudoku Solver UI (Enhanced with Scanner & Mobile support)
 *
 * Handles DOM interaction, grid rendering, keyboard & touch navigation,
 * validation feedback, mobile digit pad, camera/upload scanner integration,
 * and wiring to the solver engine (solver.js).
 */

/* ── Example Puzzles ── */
const EXAMPLES = [
  // Easy
  "530070000600195000098000060800060003400803001700020006060000280000419005000080079",
  // Medium
  "017903600000080000900000507072010430000402070064370250701000065000030000005601720",
  // Hard — AI Escargot
  "100007090030020008009600500005300900010080002600004000300000010041000007007000300",
  // Evil — minimum-clue puzzle
  "000000000000003085001020000000507000004000100090000000500000073002010000000040009",
];

/* ── State ── */
let boardValues = new Array(81).fill(0); // current board (0 = empty)
let givenMask   = new Array(81).fill(false); // true = user-entered clue
let solvedMask  = new Array(81).fill(false); // true = filled by solver
let cells       = []; // DOM cell elements
let selectedIdx = -1; // currently focused cell index

// ── Touch / Mobile Detection ──
const isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
if (isTouchDevice) {
  document.body.classList.add('has-touch');
}

// ── Scanner Review State ──
let reviewValues = new Array(81).fill(0);
let reviewConfidence = new Array(81).fill(1.0);
let reviewSelectedIdx = -1;
let reviewScanId = null;
let reviewCells = [];

// ── Camera Stream State ──
let cameraStream = null;

/* ── Build Main Grid ── */
function buildGrid() {
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  cells = [];

  for (let idx = 0; idx < 81; idx++) {
    const row = Math.floor(idx / 9);
    const col = idx % 9;

    const div = document.createElement('div');
    div.className = buildCellClass(row, col);
    div.setAttribute('role', 'gridcell');
    div.setAttribute('tabindex', '0');
    div.setAttribute('aria-label', `Row ${row + 1}, Column ${col + 1}`);

    // Click & focus handlers
    div.addEventListener('click', () => selectCell(idx));
    div.addEventListener('focus', () => selectCell(idx));

    // Keyboard inputs
    div.addEventListener('keydown', (e) => handleKey(e, idx, false));

    cells.push(div);
    grid.appendChild(div);
  }
}

/** Returns the base className string for a cell at (row, col). */
function buildCellClass(row, col, extra = '') {
  let cls = 'cell';
  cls += ` row${row} col${col}`;
  // Thick borders at 3x3 boundaries
  if (col === 2 || col === 5) cls += ' col' + col;
  if (row === 2 || row === 5) cls += ' row' + row;
  if (extra) cls += ' ' + extra;
  return cls;
}

/* ── Cell Selection & Navigation ── */
function selectCell(idx, isReview = false) {
  if (isReview) {
    if (reviewSelectedIdx >= 0) reviewCells[reviewSelectedIdx].classList.remove('selected');
    reviewSelectedIdx = idx;
    reviewCells[idx].classList.add('selected');
    reviewCells[idx].focus({ preventScroll: true });
    // Always show the review pad (not just on touch)
    document.getElementById('reviewDigitPadContainer').classList.add('active');
  } else {
    if (selectedIdx >= 0) cells[selectedIdx].classList.remove('selected');
    selectedIdx = idx;
    cells[idx].classList.add('selected');
    cells[idx].focus({ preventScroll: true });
    // Always show the digit pad (not just on touch devices)
    document.getElementById('digitPadContainer').classList.add('active');
  }
}

function handleKey(e, idx, isReview = false) {
  // Arrow Key Navigation - Stop at boundary (Strict movement, no unexpected jumps)
  const row = Math.floor(idx / 9);
  const col = idx % 9;

  switch (e.key) {
    case '1': case '2': case '3':
    case '4': case '5': case '6':
    case '7': case '8': case '9':
      e.preventDefault();
      if (isReview) {
        placeDigitReview(idx, parseInt(e.key));
      } else {
        placeDigit(idx, parseInt(e.key));
      }
      break;
    case '0': case 'Backspace': case 'Delete':
      e.preventDefault();
      if (isReview) {
        removeDigitReview(idx);
      } else {
        removeDigit(idx);
      }
      break;
    case 'ArrowRight':
      e.preventDefault();
      if (col < 8) selectCell(idx + 1, isReview);
      break;
    case 'ArrowLeft':
      e.preventDefault();
      if (col > 0) selectCell(idx - 1, isReview);
      break;
    case 'ArrowDown':
      e.preventDefault();
      if (row < 8) selectCell(idx + 9, isReview);
      break;
    case 'ArrowUp':
      e.preventDefault();
      if (row > 0) selectCell(idx - 9, isReview);
      break;
    case 'Enter':
      e.preventDefault();
      if (!isReview) solvePuzzle();
      break;
  }
}

/* ── Digit Placement & Real-time Validation ── */
function placeDigit(idx, v) {
  if (solvedMask[idx]) {
    solvedMask[idx] = false;
  }
  boardValues[idx] = v;
  givenMask[idx]   = true;
  renderCell(idx);
  
  // Real-time conflict checks & error highlighting
  runRealTimeValidation();
  updateMeta();
}

function removeDigit(idx) {
  boardValues[idx] = 0;
  givenMask[idx]   = false;
  solvedMask[idx]  = false;
  renderCell(idx);
  
  runRealTimeValidation();
  updateMeta();
}

function runRealTimeValidation() {
  clearErrors();
  
  // Local validation checks
  const validation = validateBoard(boardValues);
  if (!validation.ok) {
    setStatus(validation.msg, 'err');
    const conflicts = getConflictCells(boardValues);
    conflicts.forEach(idx => cells[idx].classList.add('error-cell'));
  } else {
    setStatus('');
  }
}

/* ── Render Main Cell ── */
function renderCell(idx, animate = false) {
  const row = Math.floor(idx / 9);
  const col = idx % 9;
  const c   = cells[idx];
  const v   = boardValues[idx];

  let cls = 'cell';
  cls += ' row' + row;
  cls += ' col' + col;
  if (idx === selectedIdx) cls += ' selected';

  if (v) {
    if (givenMask[idx])       cls += ' given';
    else if (solvedMask[idx]) {
      cls += ' solved';
      if (animate) cls += ' animate';
    }
    c.textContent = v;
    c.setAttribute('aria-label', `Row ${row + 1}, Column ${col + 1}: ${v}`);
  } else {
    c.textContent = '';
    c.setAttribute('aria-label', `Row ${row + 1}, Column ${col + 1}: empty`);
  }

  c.className = cls;
}

function renderAll() {
  for (let i = 0; i < 81; i++) renderCell(i);
}

/* ── Clear & Load Examples ── */
function clearBoard() {
  boardValues = new Array(81).fill(0);
  givenMask   = new Array(81).fill(false);
  solvedMask  = new Array(81).fill(false);
  renderAll();
  setStatus('Board cleared.');
  document.getElementById('time').textContent   = '—';
  document.getElementById('filled').textContent = '0';
  updateMeta();
}

function loadExample() {
  clearBoard();
  const puzzle = EXAMPLES[Math.floor(Math.random() * EXAMPLES.length)];
  for (let i = 0; i < 81; i++) {
    const v = parseInt(puzzle[i]);
    if (v) {
      boardValues[i] = v;
      givenMask[i]   = true;
      renderCell(i);
    }
  }
  updateMeta();
  setStatus('Example loaded — click Solve Sudoku!', 'info');
}

/* ── Solve ── */
async function solvePuzzle() {
  clearErrors();
  setStatus('Solving...', 'info');

  const board = [...boardValues];

  // 1. Pre-validate board state
  const validation = validateBoard(board);
  if (!validation.ok) {
    setStatus(validation.msg, 'err');
    const conflicts = getConflictCells(board);
    conflicts.forEach(idx => cells[idx].classList.add('error-cell'));
    return;
  }

  // 2. Call solver (API with client-side fallback)
  const result = await solveBoard(board);

  if (!result.success) {
    setStatus(result.message || 'No solution found.', 'err');
    document.getElementById('time').textContent = '—';
    return;
  }

  // 3. Apply solved values to state & render with staggered animation
  let count = 0;
  for (let i = 0; i < 81; i++) {
    if (!givenMask[i] && result.solution[i]) {
      boardValues[i] = result.solution[i];
      solvedMask[i]  = true;
      count++;
    }
  }

  // Stagger animation row by row, column within row
  for (let i = 0; i < 81; i++) {
    if (solvedMask[i]) {
      const row = Math.floor(i / 9);
      const col = i % 9;
      const delay = row * 20 + col * 5;
      setTimeout(() => {
        renderCell(i, true);
      }, delay);
    }
  }

  document.getElementById('time').textContent   = result.timeMs + 'ms';
  document.getElementById('filled').textContent = count;
  setStatus(result.message || `Solved in ${result.timeMs}ms ✓`, 'ok');
  updateMeta();
}

/* ── Error & Conflict Helpers ── */
function clearErrors() {
  cells.forEach(c => c.classList.remove('error-cell'));
}

function updateMeta() {
  document.getElementById('clues').textContent = givenMask.filter(Boolean).length;
}

function setStatus(msg, type = '') {
  const s = document.getElementById('status');
  s.textContent = msg;
  s.className   = 'status-bar' + (type ? ' ' + type : '');
}

/* ── Import / Export ── */
function exportPuzzle() {
  const str = givenMask.map((isGiven, i) => (isGiven ? boardValues[i] : '.')).join('');
  try {
    navigator.clipboard.writeText(str).then(() => {
      setStatus('Puzzle string copied to clipboard!', 'ok');
    });
  } catch (e) {
    prompt('Copy this puzzle string:', str);
  }
}

function importPuzzle() {
  const raw = prompt('Paste an 81-character puzzle string (digits 1–9, use 0 or . for empty cells):');
  if (!raw) return;

  const clean = raw.trim().replace(/\./g, '0').replace(/\s+/g, '');
  if (clean.length !== 81 || !/^[0-9]+$/.test(clean)) {
    setStatus('Invalid puzzle string — must be exactly 81 digits.', 'err');
    return;
  }

  clearBoard();
  for (let i = 0; i < 81; i++) {
    const v = parseInt(clean[i]);
    if (v) {
      boardValues[i] = v;
      givenMask[i]   = true;
      renderCell(i);
    }
  }
  updateMeta();
  setStatus('Puzzle imported — click Solve Sudoku!', 'info');
}

/* ── Theme Management ── */
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const icon = document.querySelector('.theme-icon');
  if (icon) icon.textContent = theme === 'dark' ? '🌙' : '☀️';
  localStorage.setItem('sudoku-theme', theme);
}

(function initTheme() {
  const saved = localStorage.getItem('sudoku-theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(saved || (prefersDark ? 'dark' : 'light'));
})();

document.getElementById('themeToggle').addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme');
  applyTheme(current === 'dark' ? 'light' : 'dark');
});

/* ── Touch Input Pad Handler ── */
function pressPadDigit(digit, isReview = false) {
  const index = isReview ? reviewSelectedIdx : selectedIdx;
  if (index === -1) return;

  if (isReview) {
    if (digit === 0) removeDigitReview(index);
    else placeDigitReview(index, digit);
  } else {
    if (digit === 0) removeDigit(index);
    else placeDigit(index, digit);
  }
}

/* ── Image Upload Scanner Logic ── */
function triggerUpload() {
  document.getElementById('fileInput').click();
}

async function handleFileSelect(event) {
  const file = event.target.files[0];
  if (!file) return;
  
  setStatus('Uploading and scanning image...', 'info');
  
  const formData = new FormData();
  formData.append('image', file);
  
  try {
    const response = await fetch('/api/scan', {
      method: 'POST',
      body: formData
    });
    
    if (response.ok) {
      const data = await response.json();
      if (data.success) {
        setStatus('Scan completed! Review the detected grid.', 'ok');
        openReviewModal(data.grid, data.confidence, data.scan_id, data.engine);
      } else {
        setStatus(data.message || 'Scanning failed.', 'err');
      }
    } else {
      // Server responded with an error status — it still sends a JSON
      // body with a real reason, so show that instead of a generic message.
      let detail = `HTTP ${response.status}`;
      try {
        const errData = await response.json();
        if (errData && errData.message) detail = errData.message;
      } catch (_) { /* response wasn't JSON; keep the status code */ }
      setStatus(`Server scanning error: ${detail}`, 'err');
    }
  } catch (err) {
    console.error(err);
    setStatus('Failed to connect to scanner API.', 'err');
  }
  
  // Reset file input
  event.target.value = '';
}

/* ── Camera Scanner Logic ── */
async function openCameraModal() {
  // Camera via getUserMedia requires HTTPS on mobile (except localhost).
  // Detect this early and guide the user to the file upload instead.
  const isSecure = location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  if (!isSecure) {
    setStatus(
      'Camera requires HTTPS on mobile. Use "Scan Image" instead — tap it and choose "Take Photo" from the menu.',
      'err'
    );
    // Trigger the file upload as a fallback — on mobile this shows
    // the OS picker which includes "Take Photo" without needing HTTPS.
    document.getElementById('fileInput').click();
    return;
  }

  const modal = document.getElementById('cameraModal');
  const video = document.getElementById('cameraVideo');
  
  modal.classList.add('active');
  setStatus('Starting camera stream...', 'info');
  
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false
    });
    video.srcObject = cameraStream;
    setStatus('Point camera at the Sudoku grid.');
  } catch (err) {
    console.error('Camera stream access failed:', err);
    closeCameraModal();
    if (err.name === 'NotAllowedError') {
      setStatus('Camera permission denied. Use "Scan Image" and choose "Take Photo" instead.', 'err');
    } else {
      setStatus('Unable to access camera. Use "Scan Image" and choose "Take Photo" instead.', 'err');
    }
  }
}

function closeCameraModal() {
  const modal = document.getElementById('cameraModal');
  modal.classList.remove('active');
  
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
    cameraStream = null;
  }
}

async function captureCameraImage() {
  const video = document.getElementById('cameraVideo');
  if (!video.srcObject) return;
  
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  
  closeCameraModal();
  setStatus('Analyzing captured photo...', 'info');
  
  canvas.toBlob(async (blob) => {
    const formData = new FormData();
    formData.append('image', blob, 'capture.jpg');
    
    try {
      const response = await fetch('/api/scan', {
        method: 'POST',
        body: formData
      });
      
      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          setStatus('Scan completed! Review the detected grid.', 'ok');
          openReviewModal(data.grid, data.confidence, data.scan_id, data.engine);
        } else {
          setStatus(data.message || 'Scanning failed.', 'err');
        }
      } else {
        let detail = `HTTP ${response.status}`;
        try {
          const errData = await response.json();
          if (errData && errData.message) detail = errData.message;
        } catch (_) { /* response wasn't JSON; keep the status code */ }
        setStatus(`Server scanning error: ${detail}`, 'err');
      }
    } catch (err) {
      console.error(err);
      setStatus('Failed to connect to scanner API.', 'err');
    }
  }, 'image/jpeg', 0.95);
}

/* ── Scan Review Modal Logic ── */
function openReviewModal(gridData, confidenceData, scanId, engine) {
  const modal = document.getElementById('reviewModal');
  const gridContainer = document.getElementById('reviewGrid');

  const badge = document.getElementById('reviewEngineBadge');
  if (badge) {
    if (engine === 'gemini') {
      badge.textContent = '✓ Scanned using Google Gemini';
      badge.style.color = 'var(--ok-color, #1a7f37)';
    } else if (engine === 'opencv_fallback') {
      badge.textContent = '⚠ Scanned using local fallback (less accurate) — set GEMINI_API_KEY for better results';
      badge.style.color = 'var(--warn-color, #b35900)';
    } else {
      badge.textContent = '';
    }
  }
  
  reviewValues = gridData.flat();
  reviewConfidence = confidenceData.flat();
  reviewScanId = scanId;
  reviewSelectedIdx = -1;
  reviewCells = [];
  
  gridContainer.innerHTML = '';
  
  for (let idx = 0; idx < 81; idx++) {
    const row = Math.floor(idx / 9);
    const col = idx % 9;
    const val = reviewValues[idx];
    const conf = reviewConfidence[idx];
    
    const div = document.createElement('div');
    
    // Check if confidence is low (below 0.85) to highlight for user verification
    let extraClass = '';
    if (val !== 0 && conf < 0.85) {
      extraClass = 'low-confidence';
    }
    
    div.className = buildCellClass(row, col, extraClass);
    div.setAttribute('role', 'gridcell');
    div.setAttribute('tabindex', '0');
    
    if (val !== 0) {
      div.textContent = val;
      div.classList.add('given');
    }
    
    // Navigation & editing handlers for review grid
    div.addEventListener('click', () => selectCell(idx, true));
    div.addEventListener('focus', () => selectCell(idx, true));
    div.addEventListener('keydown', (e) => handleKey(e, idx, true));
    
    reviewCells.push(div);
    gridContainer.appendChild(div);
  }
  
  modal.classList.add('active');
  
  // Select first cell by default
  setTimeout(() => selectCell(0, true), 100);
}

function closeReviewModal() {
  const modal = document.getElementById('reviewModal');
  modal.classList.remove('active');
  reviewSelectedIdx = -1;
  document.getElementById('reviewDigitPadContainer').classList.remove('active');
}

function placeDigitReview(idx, v) {
  reviewValues[idx] = v;
  
  // Set high confidence since user explicitly verified/edited it
  reviewConfidence[idx] = 1.0; 
  
  const c = reviewCells[idx];
  c.textContent = v;
  c.className = buildCellClass(Math.floor(idx / 9), idx % 9, 'given');
  
  if (idx === reviewSelectedIdx) {
    c.classList.add('selected');
  }
}

function removeDigitReview(idx) {
  reviewValues[idx] = 0;
  reviewConfidence[idx] = 0.0;
  
  const c = reviewCells[idx];
  c.textContent = '';
  c.className = buildCellClass(Math.floor(idx / 9), idx % 9);
  
  if (idx === reviewSelectedIdx) {
    c.classList.add('selected');
  }
}

async function confirmScanResult() {
  setStatus('Confirming scan and saving templates...', 'info');
  
  // Structure flat list back to 9x9 grid
  const grid = [];
  for (let r = 0; r < 9; r++) {
    grid.push(reviewValues.slice(r * 9, r * 9 + 9));
  }
  
  try {
    // Send corrections to Flask backend to learn templates
    await fetch('/api/confirm_scan', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        scan_id: reviewScanId,
        grid: grid
      })
    });
  } catch (err) {
    console.warn('Failed to send verified scan confirmation to server.', err);
  }
  
  // Load reviewValues to main board values
  boardValues = [...reviewValues];
  givenMask = reviewValues.map(v => v !== 0);
  solvedMask = new Array(81).fill(false);
  
  renderAll();
  closeReviewModal();
  runRealTimeValidation();
  updateMeta();
  
  setStatus('Sudoku scan verified and loaded! Click Solve Sudoku.', 'ok');
}

/* ── Init ── */
buildGrid();
updateMeta();
