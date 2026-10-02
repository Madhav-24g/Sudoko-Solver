/**
 * game.js — Sudoku Arena Play Mode Engine
 *
 * Implements:
 * - Puzzle Generation with Unique Solution Verification (Easy, Medium, Hard, Expert)
 * - Pointer-based Drag & Drop Number Input (Mobile touch & Desktop mouse)
 * - Dynamic Intelligent Number Pad (auto-exhausts when all solution digits placed)
 * - Candidate Pencil Notes Mode (3x3 mini-grid per cell)
 * - Hint System (reveals single cell, tracks hints)
 * - Mistake Tracker (0/3 limit with conflict feedback)
 * - Timer & Blur-Pause Overlay
 * - Multi-Step Undo / Redo Command Stack
 * - Scoring Engine & Persistent Statistics
 */

(function () {
  'use strict';

  // ── Game State ──
  const Game = {
    difficulty: 'easy', // 'easy' | 'medium' | 'hard' | 'expert'
    initialBoard: new Array(81).fill(0), // given puzzle clues
    solution: new Array(81).fill(0),     // ground-truth solution
    currentBoard: new Array(81).fill(0), // active board values
    notes: Array.from({ length: 81 }, () => new Set()), // Set of numbers 1-9 per cell
    selectedIdx: -1,
    notesMode: false,
    mistakes: 0,
    maxMistakes: 3,
    hintsUsed: 0,
    maxHints: 3,
    timerSeconds: 0,
    timerInterval: null,
    isPaused: false,
    isCompleted: false,
    undoStack: [],
    redoStack: [],
    playCells: [],
  };

  // ── Drag & Drop State ──
  const DragState = {
    isDragging: false,
    digit: null,
    ghostEl: null,
    hoveredCellIdx: -1,
    startX: 0,
    startY: 0,
    hasMoved: false,
  };

  // ── Statistics Storage Key ──
  const STATS_KEY = 'sudoku_arena_stats_v1';
  const PLAYER_KEY = 'sudoku_arena_player_name';

  function getPlayerName() {
    return localStorage.getItem(PLAYER_KEY) || '';
  }

  function setPlayerName(name) {
    localStorage.setItem(PLAYER_KEY, name.trim().slice(0, 20));
  }

  function getStats() {
    try {
      const data = localStorage.getItem(STATS_KEY);
      if (data) return JSON.parse(data);
    } catch (_) {}
    return {
      played: 0,
      completed: 0,
      abandoned: 0,
      bestTimes: { easy: null, medium: null, hard: null, expert: null },
      totalHints: 0,
      totalMistakes: 0,
      currentStreak: 0,
      bestStreak: 0,
      recentScores: [],
    };
  }

  function saveStats(stats) {
    try {
      localStorage.setItem(STATS_KEY, JSON.stringify(stats));
    } catch (_) {}
  }

  // ── Difficulty Configurations ──
  const DIFFICULTY_CONFIG = {
    easy:   { clues: 38, baseScore: 1000 },
    medium: { clues: 32, baseScore: 1800 },
    hard:   { clues: 27, baseScore: 2800 },
    expert: { clues: 23, baseScore: 4000 },
  };

  // ══════════════════════════════════════════════════════════════════════════════
  // 1. PUZZLE GENERATOR & FAST SOLVER (with Uniqueness Verification)
  // ══════════════════════════════════════════════════════════════════════════════

  function shuffle(arr) {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  function isValidPlacement(board, r, c, num) {
    const boxR = Math.floor(r / 3) * 3;
    const boxC = Math.floor(c / 3) * 3;
    for (let i = 0; i < 9; i++) {
      if (board[r * 9 + i] === num) return false;
      if (board[i * 9 + c] === num) return false;
      const br = boxR + Math.floor(i / 3);
      const bc = boxC + (i % 3);
      if (board[br * 9 + bc] === num) return false;
    }
    return true;
  }

  function fillFullBoard(board) {
    for (let i = 0; i < 81; i++) {
      if (board[i] === 0) {
        const r = Math.floor(i / 9);
        const c = i % 9;
        const nums = shuffle([1, 2, 3, 4, 5, 6, 7, 8, 9]);
        for (const num of nums) {
          if (isValidPlacement(board, r, c, num)) {
            board[i] = num;
            if (fillFullBoard(board)) return true;
            board[i] = 0;
          }
        }
        return false;
      }
    }
    return true;
  }

  function countSolutions(board, limit = 2) {
    let count = 0;

    function solveHelper() {
      let bestIdx = -1;
      let minCandidates = 10;
      let bestCandidates = [];

      for (let i = 0; i < 81; i++) {
        if (board[i] === 0) {
          const r = Math.floor(i / 9);
          const c = i % 9;
          const candidates = [];
          for (let v = 1; v <= 9; v++) {
            if (isValidPlacement(board, r, c, v)) candidates.push(v);
          }
          if (candidates.length === 0) return;
          if (candidates.length < minCandidates) {
            minCandidates = candidates.length;
            bestIdx = i;
            bestCandidates = candidates;
            if (minCandidates === 1) break;
          }
        }
      }

      if (bestIdx === -1) {
        count++;
        return;
      }

      for (const val of bestCandidates) {
        board[bestIdx] = val;
        solveHelper();
        board[bestIdx] = 0;
        if (count >= limit) return;
      }
    }

    const copy = [...board];
    solveHelper();
    return count;
  }

  function generateSudoku(diff) {
    const config = DIFFICULTY_CONFIG[diff] || DIFFICULTY_CONFIG.easy;
    const targetClues = config.clues;

    const complete = new Array(81).fill(0);
    for (let box = 0; box < 9; box += 3) {
      const nums = shuffle([1, 2, 3, 4, 5, 6, 7, 8, 9]);
      let k = 0;
      for (let r = 0; r < 3; r++) {
        for (let c = 0; c < 3; c++) {
          complete[(box + r) * 9 + (box + c)] = nums[k++];
        }
      }
    }
    fillFullBoard(complete);

    const puzzle = [...complete];
    const indices = shuffle(Array.from({ length: 81 }, (_, i) => i));

    let currentClues = 81;
    for (const idx of indices) {
      if (currentClues <= targetClues) break;

      const saved = puzzle[idx];
      puzzle[idx] = 0;

      if (countSolutions(puzzle, 2) === 1) {
        currentClues--;
      } else {
        puzzle[idx] = saved;
      }
    }

    return {
      puzzle,
      solution: complete,
      cluesCount: currentClues,
    };
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 2. DOM INITIALIZATION & BOARD RENDERING
  // ══════════════════════════════════════════════════════════════════════════════

  function initPlayMode() {
    buildPlayBoard();
    bindEvents();
    bindDragDropNumberPad();
    renderStatsView();

    const saved = loadSavedGame();
    if (saved) {
      restoreGame(saved);
    } else {
      startNewGame('easy', false);
    }
  }

  function buildPlayBoard() {
    const grid = document.getElementById('playGrid');
    if (!grid) return;
    grid.innerHTML = '';
    Game.playCells = [];

    for (let idx = 0; idx < 81; idx++) {
      const row = Math.floor(idx / 9);
      const col = idx % 9;

      const cell = document.createElement('div');
      cell.className = `cell row${row} col${col}`;
      if (col === 2 || col === 5) cell.classList.add('border-r-strong');
      if (row === 2 || row === 5) cell.classList.add('border-b-strong');
      cell.setAttribute('role', 'gridcell');
      cell.setAttribute('tabindex', '0');
      cell.dataset.index = idx;

      const valueSpan = document.createElement('span');
      valueSpan.className = 'cell-value';

      const notesGrid = document.createElement('div');
      notesGrid.className = 'cell-notes';
      for (let n = 1; n <= 9; n++) {
        const noteSpan = document.createElement('span');
        noteSpan.className = `note-item note-${n}`;
        notesGrid.appendChild(noteSpan);
      }

      cell.appendChild(valueSpan);
      cell.appendChild(notesGrid);

      cell.addEventListener('click', () => selectPlayCell(idx));
      cell.addEventListener('focus', () => selectPlayCell(idx));
      cell.addEventListener('keydown', (e) => handlePlayKey(e, idx));

      Game.playCells.push(cell);
      grid.appendChild(cell);
    }
  }

  function renderPlayCell(idx) {
    const cell = Game.playCells[idx];
    if (!cell) return;

    const v = Game.currentBoard[idx];
    const isInitial = Game.initialBoard[idx] !== 0;
    const valueSpan = cell.querySelector('.cell-value');
    const notesGrid = cell.querySelector('.cell-notes');

    cell.classList.remove('given', 'user-filled', 'error-cell', 'hint-filled');

    if (v !== 0) {
      valueSpan.textContent = v;
      notesGrid.style.display = 'none';

      if (isInitial) {
        cell.classList.add('given');
      } else {
        cell.classList.add('user-filled');
        if (v !== Game.solution[idx]) {
          cell.classList.add('error-cell');
        }
      }
    } else {
      valueSpan.textContent = '';
      const cellNotes = Game.notes[idx];
      if (cellNotes && cellNotes.size > 0) {
        notesGrid.style.display = 'grid';
        for (let n = 1; n <= 9; n++) {
          const noteSpan = notesGrid.querySelector(`.note-${n}`);
          if (noteSpan) {
            noteSpan.textContent = cellNotes.has(n) ? n : '';
          }
        }
      } else {
        notesGrid.style.display = 'none';
      }
    }
  }

  function renderAllPlayCells() {
    for (let i = 0; i < 81; i++) {
      renderPlayCell(i);
    }
    updateHighlights();
    updateDynamicNumberPad();
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 3. HIGHLIGHTING
  // ══════════════════════════════════════════════════════════════════════════════

  function selectPlayCell(idx) {
    if (Game.isPaused || Game.isCompleted) return;
    Game.selectedIdx = idx;
    updateHighlights();
  }

  function updateHighlights() {
    const sel = Game.selectedIdx;
    const targetVal = sel >= 0 ? Game.currentBoard[sel] : 0;
    const selRow = sel >= 0 ? Math.floor(sel / 9) : -1;
    const selCol = sel >= 0 ? sel % 9 : -1;
    const selBoxR = sel >= 0 ? Math.floor(selRow / 3) * 3 : -1;
    const selBoxC = sel >= 0 ? Math.floor(selCol / 3) * 3 : -1;

    for (let i = 0; i < 81; i++) {
      const cell = Game.playCells[i];
      if (!cell) continue;

      cell.classList.remove('selected', 'highlight-peer', 'highlight-match');

      if (i === sel) {
        cell.classList.add('selected');
        if (targetVal !== 0) {
          cell.classList.add('highlight-match');
        }
        continue;
      }

      if (sel >= 0) {
        const r = Math.floor(i / 9);
        const c = i % 9;
        const br = Math.floor(r / 3) * 3;
        const bc = Math.floor(c / 3) * 3;

        if (r === selRow || c === selCol || (br === selBoxR && bc === selBoxC)) {
          cell.classList.add('highlight-peer');
        }

        if (targetVal !== 0 && Game.currentBoard[i] === targetVal) {
          cell.classList.add('highlight-match');
        }
      }
    }
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 4. DRAG & DROP NUMBER INPUT ENGINE
  // ══════════════════════════════════════════════════════════════════════════════

  function bindDragDropNumberPad() {
    const pad = document.getElementById('playDigitPad');
    if (!pad) return;

    const buttons = pad.querySelectorAll('.play-pad-btn');
    buttons.forEach((btn) => {
      btn.addEventListener('pointerdown', handlePointerDown);
    });

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', handlePointerCancel);
  }

  function handlePointerDown(e) {
    if (Game.isPaused || Game.isCompleted) return;

    const btn = e.currentTarget;
    if (btn.classList.contains('exhausted')) return;

    const digit = parseInt(btn.dataset.digit, 10);
    if (!digit || digit < 1 || digit > 9) return;

    try {
      btn.setPointerCapture(e.pointerId);
    } catch (_) {}

    DragState.isDragging = true;
    DragState.digit = digit;
    DragState.startX = e.clientX;
    DragState.startY = e.clientY;
    DragState.hasMoved = false;
    DragState.hoveredCellIdx = -1;

    createDragGhost(digit, e.clientX, e.clientY);
  }

  function handlePointerMove(e) {
    if (!DragState.isDragging || !DragState.ghostEl) return;

    const dx = e.clientX - DragState.startX;
    const dy = e.clientY - DragState.startY;
    if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
      DragState.hasMoved = true;
    }

    DragState.ghostEl.style.transform = `translate3d(${e.clientX - 24}px, ${e.clientY - 24}px, 0)`;
    updateDragHoverTarget(e.clientX, e.clientY);
  }

  function handlePointerUp(e) {
    if (!DragState.isDragging) return;

    const digit = DragState.digit;
    const targetIdx = DragState.hoveredCellIdx;
    const hasMoved = DragState.hasMoved;

    cleanupDragGhost();
    clearDragHoverHighlights();

    DragState.isDragging = false;
    DragState.digit = null;

    if (hasMoved && targetIdx >= 0) {
      applyDigitInput(targetIdx, digit);
    } else if (!hasMoved) {
      if (Game.selectedIdx >= 0) {
        applyDigitInput(Game.selectedIdx, digit);
      }
    }
  }

  function handlePointerCancel() {
    if (DragState.isDragging) {
      cleanupDragGhost();
      clearDragHoverHighlights();
      DragState.isDragging = false;
      DragState.digit = null;
    }
  }

  function createDragGhost(digit, x, y) {
    cleanupDragGhost();
    const ghost = document.createElement('div');
    ghost.className = 'sudoku-drag-ghost';
    ghost.textContent = digit;
    ghost.style.transform = `translate3d(${x - 24}px, ${y - 24}px, 0)`;
    document.body.appendChild(ghost);
    DragState.ghostEl = ghost;
  }

  function cleanupDragGhost() {
    if (DragState.ghostEl) {
      DragState.ghostEl.remove();
      DragState.ghostEl = null;
    }
  }

  function updateDragHoverTarget(x, y) {
    if (DragState.ghostEl) DragState.ghostEl.style.display = 'none';
    const elem = document.elementFromPoint(x, y);
    if (DragState.ghostEl) DragState.ghostEl.style.display = 'flex';

    clearDragHoverHighlights();
    DragState.hoveredCellIdx = -1;

    if (!elem) return;
    const cell = elem.closest('#playGrid .cell');
    if (!cell) return;

    const idx = parseInt(cell.dataset.index, 10);
    if (isNaN(idx)) return;

    if (Game.initialBoard[idx] === 0) {
      cell.classList.add('drag-hover-target');
      DragState.hoveredCellIdx = idx;
    }
  }

  function clearDragHoverHighlights() {
    Game.playCells.forEach((c) => c.classList.remove('drag-hover-target'));
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 5. DYNAMIC NUMBER PAD EXHAUSTION
  // ══════════════════════════════════════════════════════════════════════════════

  function updateDynamicNumberPad() {
    const pad = document.getElementById('playDigitPad');
    if (!pad) return;

    const requiredCounts = {};
    const filledCounts = {};
    for (let d = 1; d <= 9; d++) {
      requiredCounts[d] = 0;
      filledCounts[d] = 0;
    }

    for (let i = 0; i < 81; i++) {
      const solVal = Game.solution[i];
      if (solVal >= 1 && solVal <= 9) requiredCounts[solVal]++;

      const curVal = Game.currentBoard[i];
      if (curVal === solVal && curVal >= 1 && curVal <= 9) {
        filledCounts[curVal]++;
      }
    }

    for (let d = 1; d <= 9; d++) {
      const btn = pad.querySelector(`.play-pad-btn[data-digit="${d}"]`);
      if (!btn) continue;

      const isExhausted = filledCounts[d] >= requiredCounts[d] && requiredCounts[d] > 0;
      const countRemaining = Math.max(0, requiredCounts[d] - filledCounts[d]);

      btn.classList.toggle('exhausted', isExhausted);
      btn.setAttribute('aria-disabled', isExhausted ? 'true' : 'false');

      let badge = btn.querySelector('.pad-remaining-badge');
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'pad-remaining-badge';
        btn.appendChild(badge);
      }
      badge.textContent = isExhausted ? '' : countRemaining;
    }
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 6. GAMEPLAY INPUT, NOTES, MISTAKES & UNDO/REDO
  // ══════════════════════════════════════════════════════════════════════════════

  function applyDigitInput(idx, digit) {
    if (Game.isPaused || Game.isCompleted) return;
    if (Game.initialBoard[idx] !== 0) return;

    selectPlayCell(idx);

    if (Game.notesMode) {
      toggleNote(idx, digit);
      return;
    }

    const prevVal = Game.currentBoard[idx];
    if (prevVal === digit) return;

    const prevNotes = new Set(Game.notes[idx]);
    const isMistake = digit !== Game.solution[idx];

    Game.undoStack.push({
      type: 'place',
      idx,
      prevVal,
      newVal: digit,
      prevNotes,
      wasMistake: isMistake,
    });
    Game.redoStack = [];

    Game.currentBoard[idx] = digit;
    Game.notes[idx].clear();

    if (isMistake) {
      Game.mistakes++;
      updateMistakesUI();
      showToast(`Mistake! (${Game.mistakes}/${Game.maxMistakes})`, 'err');

      if (Game.mistakes >= Game.maxMistakes) {
        triggerGameOver();
        return;
      }
    } else {
      prunePeerNotes(idx, digit);
    }

    renderPlayCell(idx);
    updateHighlights();
    updateDynamicNumberPad();
    saveActiveGame();

    checkPuzzleCompletion();
  }

  function toggleNote(idx, digit) {
    if (Game.currentBoard[idx] !== 0) return;

    const cellNotes = Game.notes[idx];
    const hadNote = cellNotes.has(digit);

    Game.undoStack.push({
      type: 'note',
      idx,
      digit,
      added: !hadNote,
    });
    Game.redoStack = [];

    if (hadNote) cellNotes.delete(digit);
    else cellNotes.add(digit);

    renderPlayCell(idx);
    saveActiveGame();
  }

  function prunePeerNotes(idx, digit) {
    const row = Math.floor(idx / 9);
    const col = idx % 9;
    const boxR = Math.floor(row / 3) * 3;
    const boxC = Math.floor(col / 3) * 3;

    for (let i = 0; i < 81; i++) {
      const r = Math.floor(i / 9);
      const c = i % 9;
      const br = Math.floor(r / 3) * 3;
      const bc = Math.floor(c / 3) * 3;

      if (r === row || c === col || (br === boxR && bc === boxC)) {
        if (Game.notes[i].delete(digit)) {
          renderPlayCell(i);
        }
      }
    }
  }

  function eraseSelectedCell() {
    const idx = Game.selectedIdx;
    if (idx < 0 || Game.initialBoard[idx] !== 0) return;

    const prevVal = Game.currentBoard[idx];
    const prevNotes = new Set(Game.notes[idx]);

    if (prevVal === 0 && prevNotes.size === 0) return;

    Game.undoStack.push({
      type: 'erase',
      idx,
      prevVal,
      prevNotes,
    });
    Game.redoStack = [];

    Game.currentBoard[idx] = 0;
    Game.notes[idx].clear();

    renderPlayCell(idx);
    updateHighlights();
    updateDynamicNumberPad();
    saveActiveGame();
  }

  function undoAction() {
    if (Game.undoStack.length === 0 || Game.isPaused || Game.isCompleted) return;

    const action = Game.undoStack.pop();
    Game.redoStack.push(action);

    if (action.type === 'place') {
      Game.currentBoard[action.idx] = action.prevVal;
      Game.notes[action.idx] = new Set(action.prevNotes);
      if (action.wasMistake && Game.mistakes > 0) {
        Game.mistakes--;
        updateMistakesUI();
      }
    } else if (action.type === 'note') {
      if (action.added) {
        Game.notes[action.idx].delete(action.digit);
      } else {
        Game.notes[action.idx].add(action.digit);
      }
    } else if (action.type === 'erase') {
      Game.currentBoard[action.idx] = action.prevVal;
      Game.notes[action.idx] = new Set(action.prevNotes);
    } else if (action.type === 'hint') {
      Game.currentBoard[action.idx] = 0;
      if (Game.hintsUsed > 0) Game.hintsUsed--;
      updateHintsUI();
    }

    renderPlayCell(action.idx);
    selectPlayCell(action.idx);
    updateDynamicNumberPad();
    saveActiveGame();
  }

  function redoAction() {
    if (Game.redoStack.length === 0 || Game.isPaused || Game.isCompleted) return;

    const action = Game.redoStack.pop();
    Game.undoStack.push(action);

    if (action.type === 'place') {
      Game.currentBoard[action.idx] = action.newVal;
      Game.notes[action.idx].clear();
      if (action.wasMistake) {
        Game.mistakes++;
        updateMistakesUI();
      }
    } else if (action.type === 'note') {
      if (action.added) {
        Game.notes[action.idx].add(action.digit);
      } else {
        Game.notes[action.idx].delete(action.digit);
      }
    } else if (action.type === 'erase') {
      Game.currentBoard[action.idx] = 0;
      Game.notes[action.idx].clear();
    } else if (action.type === 'hint') {
      Game.currentBoard[action.idx] = action.val;
      Game.hintsUsed++;
      updateHintsUI();
    }

    renderPlayCell(action.idx);
    selectPlayCell(action.idx);
    updateDynamicNumberPad();
    saveActiveGame();
  }

  function provideHint() {
    if (Game.isPaused || Game.isCompleted) return;

    if (Game.hintsUsed >= Game.maxHints) {
      showToast(`No hints remaining (${Game.maxHints}/${Game.maxHints} used)`, 'info');
      return;
    }

    let targetIdx = -1;

    // Check if player has an active cell selected
    if (Game.selectedIdx >= 0 && Game.selectedIdx < 81) {
      const sel = Game.selectedIdx;
      if (Game.initialBoard[sel] !== 0) {
        showToast("That's an original clue cell. Tap an empty cell to get a hint!", 'info');
        return;
      }
      if (Game.currentBoard[sel] === Game.solution[sel]) {
        showToast("This cell is already correct!", 'info');
        return;
      }
      targetIdx = sel;
    }

    // If no unsolved cell is selected, pick a random unsolved cell across the board
    if (targetIdx === -1) {
      const candidates = [];
      for (let i = 0; i < 81; i++) {
        if (Game.initialBoard[i] === 0 && Game.currentBoard[i] !== Game.solution[i]) {
          candidates.push(i);
        }
      }
      if (candidates.length === 0) return;
      targetIdx = candidates[Math.floor(Math.random() * candidates.length)];
    }

    const correctVal = Game.solution[targetIdx];
    Game.hintsUsed++;
    updateHintsUI();

    Game.undoStack.push({
      type: 'hint',
      idx: targetIdx,
      val: correctVal,
    });
    Game.redoStack = [];

    Game.currentBoard[targetIdx] = correctVal;
    Game.notes[targetIdx].clear();

    const cell = Game.playCells[targetIdx];
    renderPlayCell(targetIdx);
    cell.classList.add('hint-filled');
    selectPlayCell(targetIdx);

    prunePeerNotes(targetIdx, correctVal);
    updateDynamicNumberPad();
    saveActiveGame();

    const row = Math.floor(targetIdx / 9) + 1;
    const col = (targetIdx % 9) + 1;
    showToast(`💡 Hint (${Game.hintsUsed}/${Game.maxHints}): Placed ${correctVal} at Row ${row}, Col ${col}`, 'ok');

    checkPuzzleCompletion();
  }

  function handlePlayKey(e, idx) {
    if (Game.isPaused || Game.isCompleted) return;

    const row = Math.floor(idx / 9);
    const col = idx % 9;

    switch (e.key) {
      case '1': case '2': case '3':
      case '4': case '5': case '6':
      case '7': case '8': case '9':
        e.preventDefault();
        applyDigitInput(idx, parseInt(e.key, 10));
        break;
      case 'Backspace': case 'Delete': case '0':
        e.preventDefault();
        eraseSelectedCell();
        break;
      case 'ArrowRight':
        e.preventDefault();
        if (col < 8) selectPlayCell(idx + 1);
        break;
      case 'ArrowLeft':
        e.preventDefault();
        if (col > 0) selectPlayCell(idx - 1);
        break;
      case 'ArrowDown':
        e.preventDefault();
        if (row < 8) selectPlayCell(idx + 9);
        break;
      case 'ArrowUp':
        e.preventDefault();
        if (row > 0) selectPlayCell(idx - 9);
        break;
      case 'h': case 'H':
        e.preventDefault();
        provideHint();
        break;
      case 'z': case 'Z':
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          if (e.shiftKey) redoAction();
          else undoAction();
        }
        break;
      case 'y': case 'Y':
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          redoAction();
        }
        break;
    }
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 7. TIMER & PAUSE OVERLAY
  // ══════════════════════════════════════════════════════════════════════════════

  function startTimer() {
    stopTimer();
    Game.timerInterval = setInterval(() => {
      if (!Game.isPaused && !Game.isCompleted) {
        Game.timerSeconds++;
        updateTimerDisplay();
      }
    }, 1000);
  }

  function stopTimer() {
    if (Game.timerInterval) {
      clearInterval(Game.timerInterval);
      Game.timerInterval = null;
    }
  }

  function formatTime(totalSec) {
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  function updateTimerDisplay() {
    const el = document.getElementById('playTimer');
    if (el) el.textContent = formatTime(Game.timerSeconds);
  }

  function togglePause() {
    if (Game.isCompleted) return;

    Game.isPaused = !Game.isPaused;
    const overlay = document.getElementById('pauseOverlay');
    const btn = document.getElementById('pauseBtn');

    if (Game.isPaused) {
      if (overlay) overlay.classList.add('active');
      if (btn) btn.innerHTML = '<span class="icon">▶</span> Resume';
    } else {
      if (overlay) overlay.classList.remove('active');
      if (btn) btn.innerHTML = '<span class="icon">⏸</span> Pause';
    }
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 8. COMPLETION & SCORING SYSTEM
  // ══════════════════════════════════════════════════════════════════════════════

  function checkPuzzleCompletion() {
    for (let i = 0; i < 81; i++) {
      if (Game.currentBoard[i] !== Game.solution[i]) {
        return false;
      }
    }

    stopTimer();
    Game.isCompleted = true;

    const score = calculateScore();
    recordGameCompletion(score);
    showCompletionModal(score);
    return true;
  }

  function calculateScore() {
    const base = DIFFICULTY_CONFIG[Game.difficulty]?.baseScore || 1000;
    const timePenalty = Math.floor(Game.timerSeconds * 0.5);
    const mistakePenalty = Game.mistakes * 150;
    const hintPenalty = Game.hintsUsed * 200;

    const finalScore = Math.max(100, base - timePenalty - mistakePenalty - hintPenalty);
    return finalScore;
  }

  function showCompletionModal(score) {
    const modal = document.getElementById('completionModal');
    if (!modal) return;

    document.getElementById('compDifficulty').textContent = capitalize(Game.difficulty);
    document.getElementById('compTime').textContent = formatTime(Game.timerSeconds);
    document.getElementById('compMistakes').textContent = `${Game.mistakes} / ${Game.maxMistakes}`;
    document.getElementById('compHints').textContent = `${Game.hintsUsed} / ${Game.maxHints}`;
    document.getElementById('compScore').textContent = score;

    modal.classList.add('active');
    localStorage.removeItem('sudoku_arena_active_game');
  }

  function triggerGameOver() {
    stopTimer();
    Game.isCompleted = true;

    const stats = getStats();
    stats.played++;
    stats.abandoned++;
    stats.currentStreak = 0;
    saveStats(stats);
    renderStatsView();

    localStorage.removeItem('sudoku_arena_active_game');
    alert(`Game Over! You reached ${Game.maxMistakes} mistakes. Try a new game!`);
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 9. NEW GAME & STATE PERSISTENCE
  // ══════════════════════════════════════════════════════════════════════════════

  function startNewGame(diff = 'easy', confirmIfActive = true) {
    if (confirmIfActive && !Game.isCompleted && Game.timerSeconds > 10) {
      if (!confirm('Start a new puzzle? Your current progress will be lost.')) {
        return;
      }
      const stats = getStats();
      stats.played++;
      stats.abandoned++;
      stats.currentStreak = 0;
      saveStats(stats);
    }

    Game.difficulty = diff;
    Game.isCompleted = false;
    Game.isPaused = false;
    Game.mistakes = 0;
    Game.hintsUsed = 0;
    Game.timerSeconds = 0;
    Game.selectedIdx = -1;
    Game.undoStack = [];
    Game.redoStack = [];
    Game.notes = Array.from({ length: 81 }, () => new Set());

    showToast(`Generating ${capitalize(diff)} puzzle...`, 'info');
    const { puzzle, solution } = generateSudoku(diff);

    Game.initialBoard = [...puzzle];
    Game.solution = [...solution];
    Game.currentBoard = [...puzzle];

    const compModal = document.getElementById('completionModal');
    if (compModal) compModal.classList.remove('active');
    const pauseOverlay = document.getElementById('pauseOverlay');
    if (pauseOverlay) pauseOverlay.classList.remove('active');

    updateDifficultyPillsUI(diff);
    updateMistakesUI();
    updateHintsUI();
    updateTimerDisplay();

    renderAllPlayCells();
    startTimer();
    saveActiveGame();

    showToast(`${capitalize(diff)} puzzle ready! Good luck!`, 'ok');
  }

  function saveActiveGame() {
    if (Game.isCompleted) return;
    try {
      const state = {
        difficulty: Game.difficulty,
        initialBoard: Game.initialBoard,
        solution: Game.solution,
        currentBoard: Game.currentBoard,
        notes: Game.notes.map((s) => Array.from(s)),
        mistakes: Game.mistakes,
        hintsUsed: Game.hintsUsed,
        timerSeconds: Game.timerSeconds,
      };
      localStorage.setItem('sudoku_arena_active_game', JSON.stringify(state));
    } catch (_) {}
  }

  function loadSavedGame() {
    try {
      const data = localStorage.getItem('sudoku_arena_active_game');
      if (data) return JSON.parse(data);
    } catch (_) {}
    return null;
  }

  function restoreGame(saved) {
    Game.difficulty = saved.difficulty || 'easy';
    Game.initialBoard = saved.initialBoard;
    Game.solution = saved.solution;
    Game.currentBoard = saved.currentBoard;
    Game.notes = saved.notes.map((arr) => new Set(arr));
    Game.mistakes = saved.mistakes || 0;
    Game.hintsUsed = saved.hintsUsed || 0;
    Game.timerSeconds = saved.timerSeconds || 0;
    Game.isCompleted = false;
    Game.isPaused = false;
    Game.selectedIdx = 0;

    updateDifficultyPillsUI(Game.difficulty);
    updateMistakesUI();
    updateHintsUI();
    updateTimerDisplay();

    renderAllPlayCells();
    selectPlayCell(0);
    startTimer();
  }

  function recordGameCompletion(score) {
    const stats = getStats();
    stats.played++;
    stats.completed++;
    stats.currentStreak++;
    stats.bestStreak = Math.max(stats.bestStreak, stats.currentStreak);
    stats.totalHints += Game.hintsUsed;
    stats.totalMistakes += Game.mistakes;

    const curBest = stats.bestTimes[Game.difficulty];
    if (curBest === null || Game.timerSeconds < curBest) {
      stats.bestTimes[Game.difficulty] = Game.timerSeconds;
    }

    stats.recentScores.unshift({
      difficulty: Game.difficulty,
      score,
      time: Game.timerSeconds,
      mistakes: Game.mistakes,
      date: new Date().toLocaleDateString(),
    });
    if (stats.recentScores.length > 20) stats.recentScores.pop();

    saveStats(stats);
    renderStatsView();

    // Post score to global server leaderboard (fire-and-forget)
    postScoreToServer(score);
  }

  async function postScoreToServer(score) {
    try {
      // Ask for player name once if not set
      let name = getPlayerName();
      if (!name) {
        name = (prompt('🏆 New high score! Enter your name for the global leaderboard (leave blank for Anonymous):') || '').trim();
        if (name) setPlayerName(name);
        else name = 'Anonymous';
      }

      const res = await fetch('/api/leaderboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          difficulty: Game.difficulty,
          score,
          time: Game.timerSeconds,
          date: new Date().toLocaleDateString(),
        }),
      });

      if (!res.ok) return;
      const data = await res.json();
      if (data.success && data.is_top) {
        showToast(`🏆 Rank #${data.rank} on global leaderboard!`, 'success');
      }
    } catch (_) {
      // Silently fail — offline or server down
    }
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 10. UI HELPERS & NAVIGATION
  // ══════════════════════════════════════════════════════════════════════════════

  function updateMistakesUI() {
    const el = document.getElementById('playMistakes');
    if (el) el.textContent = `${Game.mistakes}/${Game.maxMistakes} Mistakes`;
  }

  function updateHintsUI() {
    const el = document.getElementById('hintCountBadge');
    if (el) el.textContent = `${Game.maxHints - Game.hintsUsed}`;
  }

  function updateDifficultyPillsUI(diff) {
    document.querySelectorAll('.diff-pill').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.diff === diff);
    });
  }

  function toggleNotesMode() {
    Game.notesMode = !Game.notesMode;
    const btn = document.getElementById('notesToggleBtn');
    if (btn) {
      btn.classList.toggle('active', Game.notesMode);
      const label = btn.querySelector('.btn-label');
      if (label) label.textContent = Game.notesMode ? 'Notes: ON' : 'Notes: OFF';
    }
    showToast(Game.notesMode ? 'Pencil Notes Mode: ON' : 'Pencil Notes Mode: OFF', 'info');
  }

  function showToast(msg, type = '') {
    let toast = document.getElementById('sudokuToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'sudokuToast';
      toast.className = 'sudoku-toast';
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.className = `sudoku-toast ${type} show`;
    clearTimeout(toast._timeout);
    toast._timeout = setTimeout(() => {
      toast.classList.remove('show');
    }, 2400);
  }

  function capitalize(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
  }

  function renderStatsView() {
    const stats = getStats();
    const setVal = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    setVal('statGamesPlayed', stats.played);
    setVal('statGamesWon', stats.completed);
    setVal('statWinRate', stats.played > 0 ? `${Math.round((stats.completed / stats.played) * 100)}%` : '0%');
    setVal('statCurrentStreak', stats.currentStreak);
    setVal('statBestStreak', stats.bestStreak);

    setVal('statBestEasy', stats.bestTimes.easy ? formatTime(stats.bestTimes.easy) : '—');
    setVal('statBestMedium', stats.bestTimes.medium ? formatTime(stats.bestTimes.medium) : '—');
    setVal('statBestHard', stats.bestTimes.hard ? formatTime(stats.bestTimes.hard) : '—');
    setVal('statBestExpert', stats.bestTimes.expert ? formatTime(stats.bestTimes.expert) : '—');

    const tbody = document.getElementById('leaderboardBody');
    if (tbody) {
      tbody.innerHTML = '';
      if (stats.recentScores.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">No games completed yet. Play your first puzzle!</td></tr>';
      } else {
        stats.recentScores.forEach((item, index) => {
          const row = document.createElement('tr');
          row.innerHTML = `
            <td>#${index + 1}</td>
            <td><span class="badge-diff ${item.difficulty}">${capitalize(item.difficulty)}</span></td>
            <td><strong>${item.score}</strong></td>
            <td>${formatTime(item.time)}</td>
            <td>${item.date}</td>
          `;
          tbody.appendChild(row);
        });
      }
    }
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 11. BIND BUTTON EVENTS
  // ══════════════════════════════════════════════════════════════════════════════

  function bindEvents() {
    document.querySelectorAll('.diff-pill').forEach((btn) => {
      btn.addEventListener('click', () => {
        const diff = btn.dataset.diff;
        startNewGame(diff, true);
      });
    });

    document.getElementById('notesToggleBtn')?.addEventListener('click', toggleNotesMode);
    document.getElementById('eraseBtn')?.addEventListener('click', eraseSelectedCell);
    document.getElementById('undoBtn')?.addEventListener('click', undoAction);
    document.getElementById('redoBtn')?.addEventListener('click', redoAction);
    document.getElementById('hintBtn')?.addEventListener('click', provideHint);
    document.getElementById('newGameBtn')?.addEventListener('click', () => startNewGame(Game.difficulty, true));
    document.getElementById('pauseBtn')?.addEventListener('click', togglePause);
    document.getElementById('resumeBtn')?.addEventListener('click', togglePause);
    document.getElementById('playBackBtn')?.addEventListener('click', () => {
      window.switchAppView('viewHome');
    });

    document.getElementById('compPlayAgainBtn')?.addEventListener('click', () => {
      startNewGame(Game.difficulty, false);
    });
    document.getElementById('compDiffBtn')?.addEventListener('click', () => {
      const modal = document.getElementById('completionModal');
      if (modal) modal.classList.remove('active');
    });
    document.getElementById('compStatsBtn')?.addEventListener('click', () => {
      const modal = document.getElementById('completionModal');
      if (modal) modal.classList.remove('active');
      window.switchAppView('viewStats');
    });
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 12. TAB / VIEW NAVIGATION
  // ══════════════════════════════════════════════════════════════════════════════

  window.switchAppView = function (targetViewId) {
    const views = ['viewHome', 'viewPlay', 'viewSolver', 'viewStats', 'viewGuide', 'viewLeaderboard'];
    views.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.style.display = id === targetViewId ? 'block' : 'none';
    });

    // Toggle play-active to enable zero-scroll mobile immersive game layout
    document.body.classList.toggle('play-active', targetViewId === 'viewPlay');

    document.querySelectorAll('.nav-tab').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.target === targetViewId);
    });

    if (targetViewId === 'viewStats') {
      renderStatsView();
    }
    if (targetViewId === 'viewLeaderboard') {
      renderStatsView();
      fetchGlobalLeaderboard();
    }
  };

  window.SudokuGame = {
    init: initPlayMode,
    startNewGame,
    switchView: window.switchAppView,
  };

  // ── Global Leaderboard ──────────────────────────────────────────────────────

  async function fetchGlobalLeaderboard() {
    const tbody = document.getElementById('globalLeaderboardBody');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">Loading global scores…</td></tr>';

    // Also handle difficulty filter
    const activePill = document.querySelector('.lb-filter-pill.active');
    const diff = activePill?.dataset.diff || '';
    const url = diff ? `/api/leaderboard?difficulty=${diff}` : '/api/leaderboard';

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderGlobalLeaderboard(data.leaderboard, diff);
    } catch (err) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--error);">Could not load global leaderboard. Is the server running?</td></tr>';
    }
  }

  function renderGlobalLeaderboard(leaderboard, filterDiff = '') {
    const tbody = document.getElementById('globalLeaderboardBody');
    if (!tbody) return;

    // Flatten entries across difficulties (or just the filtered one)
    let entries = [];
    if (filterDiff && leaderboard[filterDiff]) {
      entries = leaderboard[filterDiff].map(e => ({ ...e, _diff: filterDiff }));
    } else {
      for (const diff of ['easy', 'medium', 'hard', 'expert']) {
        if (leaderboard[diff]) {
          leaderboard[diff].forEach(e => entries.push({ ...e, _diff: diff }));
        }
      }
      // Sort combined list: score desc, time asc
      entries.sort((a, b) => b.score - a.score || a.time - b.time);
      entries = entries.slice(0, 20);
    }

    tbody.innerHTML = '';
    if (entries.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">No scores yet — be the first to complete a puzzle!</td></tr>';
      return;
    }

    entries.forEach((e, idx) => {
      const rank = idx + 1;
      const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : `#${rank}`;
      const row = document.createElement('tr');
      if (rank <= 3) row.classList.add('top-rank');
      row.innerHTML = `
        <td><strong>${medal}</strong></td>
        <td>${escHtml(e.name)}</td>
        <td><span class="badge-diff ${e._diff}">${capitalize(e._diff)}</span></td>
        <td><strong>${e.score}</strong></td>
        <td>${formatTime(e.time)}</td>
      `;
      tbody.appendChild(row);
    });
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Expose for inline onclick handlers in HTML
  window.fetchGlobalLeaderboard = fetchGlobalLeaderboard;
  window.setLbFilter = function (diff, btn) {
    document.querySelectorAll('.lb-filter-pill').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    fetchGlobalLeaderboard();
  };
  window.setPlayerNamePrompt = function () {
    const current = getPlayerName();
    const name = (prompt('Enter your display name for the global leaderboard:', current) || '').trim();
    if (name) {
      setPlayerName(name);
      showToast(`Name set to "${name}" — appears on next score submission.`, 'info');
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPlayMode);
  } else {
    initPlayMode();
  }
})();
