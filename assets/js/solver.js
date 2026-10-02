/**
 * solver.js — Optimized Sudoku Solver (with API Backend integration and Client-Side Fallback)
 *
 * This file handles solving the board using either the mathematically rigorous 
 * Python Flask backend (supporting uniqueness checks and detailed validation) 
 * or the client-side MRV Backtracking solver as a fallback.
 */

/**
 * Solves a Sudoku puzzle.
 * Attempts to use the Python backend API first. If it fails or is unreachable,
 * falls back to the client-side backtracking solver.
 * 
 * @param {number[]} board - 81-element array, 0 = empty, 1-9 = given.
 * @returns {Promise<{success: boolean, solution?: number[], status?: string, message?: string, timeMs?: number}>}
 */
async function solveBoard(board) {
  // Convert 81-element array to 9x9 nested array for the Python API
  const grid = [];
  for (let r = 0; r < 9; r++) {
    grid.push(board.slice(r * 9, r * 9 + 9));
  }

  try {
    const response = await fetch('/api/solve', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ grid }),
    });

    if (response.ok) {
      const data = await response.json();
      if (data.success && data.solution) {
        // Flatten 9x9 solution back to 81-element array
        const flatSolution = data.solution.flat();
        return {
          success: true,
          solution: flatSolution,
          status: data.status,
          message: data.message,
          timeMs: data.solve_time_ms
        };
      } else {
        return {
          success: false,
          status: data.status,
          message: data.message || 'Solver failed to find a unique solution.'
        };
      }
    }
  } catch (err) {
    console.warn('Backend solver API unreachable. Falling back to local client-side solver.', err);
  }

  // ── Client-Side Fallback ──────────────────────────────────────────────────
  const t0 = performance.now();
  const boardCopy = [...board];
  const solved = localSolveBoard(boardCopy);
  const t1 = performance.now();

  if (solved) {
    return {
      success: true,
      solution: boardCopy,
      status: 'unique',
      message: 'Solved locally using client-side fallback (uniqueness not checked).',
      timeMs: parseFloat((t1 - t0).toFixed(2))
    };
  } else {
    return {
      success: false,
      status: 'unsolvable',
      message: 'Local solver determined the puzzle is unsolvable.'
    };
  }
}

/**
 * Validates a board for duplicate violations (used locally).
 * @param {number[]} board
 * @returns {{ ok: boolean, msg?: string }}
 */
function validateBoard(board) {
  for (let i = 0; i < 9; i++) {
    const rowSeen = {};
    const colSeen = {};
    const boxSeen = {};

    for (let j = 0; j < 9; j++) {
      // Row check
      const rv = board[i * 9 + j];
      if (rv) {
        if (rowSeen[rv] !== undefined) return { ok: false, msg: `Duplicate ${rv} in row ${i + 1}` };
        rowSeen[rv] = i * 9 + j;
      }

      // Column check
      const cv = board[j * 9 + i];
      if (cv) {
        if (colSeen[cv] !== undefined) return { ok: false, msg: `Duplicate ${cv} in column ${i + 1}` };
        colSeen[cv] = j * 9 + i;
      }

      // 3×3 box check
      const boxRow = Math.floor(i / 3) * 3 + Math.floor(j / 3);
      const boxCol = (i % 3) * 3 + (j % 3);
      const bv = board[boxRow * 9 + boxCol];
      if (bv) {
        if (boxSeen[bv] !== undefined) return { ok: false, msg: `Duplicate ${bv} in a 3×3 box` };
        boxSeen[bv] = boxRow * 9 + boxCol;
      }
    }
  }
  return { ok: true };
}

/**
 * Returns the indices of all cells that form constraint violations.
 * Used to highlight conflicting cells in red.
 * @param {number[]} board
 * @returns {Set<number>}
 */
function getConflictCells(board) {
  const bad = new Set();

  for (let i = 0; i < 9; i++) {
    const rowSeen = {};
    const colSeen = {};
    const boxSeen = {};

    for (let j = 0; j < 9; j++) {
      const ri = i * 9 + j;
      const ci = j * 9 + i;
      const br = Math.floor(i / 3) * 3 + Math.floor(j / 3);
      const bc = (i % 3) * 3 + (j % 3);
      const bi = br * 9 + bc;

      const rv = board[ri];
      const cv = board[ci];
      const bv = board[bi];

      if (rv) {
        if (rowSeen[rv] !== undefined) { bad.add(ri); bad.add(rowSeen[rv]); }
        else rowSeen[rv] = ri;
      }
      if (cv) {
        if (colSeen[cv] !== undefined) { bad.add(ci); bad.add(colSeen[cv]); }
        else colSeen[cv] = ci;
      }
      if (bv) {
        if (boxSeen[bv] !== undefined) { bad.add(bi); bad.add(boxSeen[bv]); }
        else boxSeen[bv] = bi;
      }
    }
  }

  return bad;
}

/**
 * Recursive backtracking with MRV cell selection (local fallback).
 * @param {number[]} board
 * @returns {boolean}
 */
function localSolveBoard(board) {
  const rows = Array.from({ length: 9 }, () => new Set());
  const cols = Array.from({ length: 9 }, () => new Set());
  const boxs = Array.from({ length: 9 }, () => new Set());

  for (let i = 0; i < 81; i++) {
    const v = board[i];
    if (v !== 0) {
      const r = Math.floor(i / 9);
      const c = i % 9;
      const b = Math.floor(r / 3) * 3 + Math.floor(c / 3);
      rows[r].add(v);
      cols[c].add(v);
      boxs[b].add(v);
    }
  }

  return localBacktrack(board, rows, cols, boxs);
}

function localBacktrack(board, rows, cols, boxs) {
  let bestIdx = -1;
  let bestCount = 10;

  for (let i = 0; i < 81; i++) {
    if (board[i] !== 0) continue;

    const r = Math.floor(i / 9);
    const c = i % 9;
    const b = Math.floor(r / 3) * 3 + Math.floor(c / 3);

    let count = 0;
    for (let v = 1; v <= 9; v++) {
      if (!rows[r].has(v) && !cols[c].has(v) && !boxs[b].has(v)) count++;
    }

    if (count === 0) return false;

    if (count < bestCount) {
      bestCount = count;
      bestIdx = i;
      if (count === 1) break;
    }
  }

  if (bestIdx === -1) return true;

  const r = Math.floor(bestIdx / 9);
  const c = bestIdx % 9;
  const b = Math.floor(r / 3) * 3 + Math.floor(c / 3);

  for (let v = 1; v <= 9; v++) {
    if (rows[r].has(v) || cols[c].has(v) || boxs[b].has(v)) continue;

    board[bestIdx] = v;
    rows[r].add(v); cols[c].add(v); boxs[b].add(v);

    if (localBacktrack(board, rows, cols, boxs)) return true;

    board[bestIdx] = 0;
    rows[r].delete(v); cols[c].delete(v); boxs[b].delete(v);
  }

  return false;
}
