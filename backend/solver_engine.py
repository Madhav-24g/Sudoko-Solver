"""
solver_engine.py — Mathematically Rigorous Sudoku Solver

Implements:
- Constraint Propagation (Naked Singles, Hidden Singles, Candidate Elimination)
- Backtracking with Minimum Remaining Values (MRV) Heuristic
- Uniqueness Detection (detects puzzles with multiple solutions)
- Full validation of input and output

Every returned solution is verified against all Sudoku rules.
No guessing, no shortcuts, no incorrect solutions.
"""


def solve_puzzle(grid):
    """
    Solve a Sudoku puzzle with full validation and uniqueness detection.

    Args:
        grid: 9x9 list of lists, 0 = empty, 1-9 = given digit

    Returns:
        dict with keys:
            success (bool): True if a solution was found (unique or not)
            solution (list|None): 9x9 solved grid, or None if invalid/unsolvable
            status (str): 'unique' | 'multiple' | 'invalid' | 'unsolvable'
                - 'unique': exactly one solution exists; it is returned
                - 'multiple': more than one solution exists; one of them is
                  still returned (caller asked for "any valid solution")
                - 'invalid': malformed grid or rule violation in the givens
                - 'unsolvable': no valid completion exists
            message (str): Human-readable explanation
    """
    # 1. Validate input grid
    error = validate_grid(grid)
    if error:
        return {
            'success': False,
            'solution': None,
            'status': 'invalid',
            'message': error
        }

    # 2. Find solutions (up to 2 to detect uniqueness)
    solutions = _find_solutions(grid, max_solutions=2)

    if len(solutions) == 0:
        return {
            'success': False,
            'solution': None,
            'status': 'unsolvable',
            'message': 'No valid solution exists for this puzzle.'
        }

    # 3. Verify the (first) solution satisfies every Sudoku rule
    solution = solutions[0]
    if not _is_valid_complete(solution):
        return {
            'success': False,
            'solution': None,
            'status': 'invalid',
            'message': 'Internal solver error — produced invalid solution. Please report this puzzle.'
        }

    if len(solutions) > 1:
        # Multiple solutions exist — still return one valid completion,
        # but flag that it isn't the unique mathematical answer.
        return {
            'success': True,
            'solution': solution,
            'status': 'multiple',
            'message': 'Puzzle has multiple valid solutions — showing one of them.'
        }

    return {
        'success': True,
        'solution': solution,
        'status': 'unique',
        'message': 'Puzzle solved successfully with a unique solution.'
    }


def validate_grid(grid):
    """
    Validate grid structure and constraints.

    Returns:
        str: Error message, or None if valid
    """
    # Structural checks
    if not grid or len(grid) != 9:
        return 'Grid must be exactly 9 rows.'

    for i, row in enumerate(grid):
        if not row or len(row) != 9:
            return f'Row {i + 1} must have exactly 9 cells.'
        for j, val in enumerate(row):
            if not isinstance(val, int) or val < 0 or val > 9:
                return f'Cell at row {i + 1}, column {j + 1} has invalid value: {val}. Must be 0-9.'

    # Check for duplicates in rows
    for i in range(9):
        seen = {}
        for j in range(9):
            v = grid[i][j]
            if v != 0:
                if v in seen:
                    return f'Duplicate {v} in row {i + 1} (columns {seen[v] + 1} and {j + 1}).'
                seen[v] = j

    # Check for duplicates in columns
    for j in range(9):
        seen = {}
        for i in range(9):
            v = grid[i][j]
            if v != 0:
                if v in seen:
                    return f'Duplicate {v} in column {j + 1} (rows {seen[v] + 1} and {i + 1}).'
                seen[v] = i

    # Check for duplicates in 3x3 boxes
    for box_r in range(3):
        for box_c in range(3):
            seen = {}
            for r in range(3):
                for c in range(3):
                    row, col = box_r * 3 + r, box_c * 3 + c
                    v = grid[row][col]
                    if v != 0:
                        if v in seen:
                            prev_r, prev_c = seen[v]
                            return (f'Duplicate {v} in box ({box_r + 1}, {box_c + 1}) '
                                    f'at ({prev_r + 1},{prev_c + 1}) and ({row + 1},{col + 1}).')
                        seen[v] = (row, col)

    return None  # Valid


def get_conflicts(grid):
    """
    Find all cells involved in constraint violations.

    Returns:
        list of [row, col] pairs for all conflicting cells
    """
    conflicts = set()

    # Row conflicts
    for i in range(9):
        seen = {}
        for j in range(9):
            v = grid[i][j]
            if v != 0:
                if v in seen:
                    conflicts.add((i, seen[v]))
                    conflicts.add((i, j))
                else:
                    seen[v] = j

    # Column conflicts
    for j in range(9):
        seen = {}
        for i in range(9):
            v = grid[i][j]
            if v != 0:
                if v in seen:
                    conflicts.add((seen[v], j))
                    conflicts.add((i, j))
                else:
                    seen[v] = i

    # Box conflicts
    for box_r in range(3):
        for box_c in range(3):
            seen = {}
            for r in range(3):
                for c in range(3):
                    row, col = box_r * 3 + r, box_c * 3 + c
                    v = grid[row][col]
                    if v != 0:
                        if v in seen:
                            prev = seen[v]
                            conflicts.add(prev)
                            conflicts.add((row, col))
                        else:
                            seen[v] = (row, col)

    return [[r, c] for r, c in conflicts]


# ── Internal Solver ──────────────────────────────────────────────────────────


def _find_solutions(grid, max_solutions=2):
    """
    Find all solutions (up to max_solutions) using constraint propagation
    and backtracking with MRV heuristic.
    """
    # Deep copy the grid
    puzzle = [row[:] for row in grid]

    # Initialize candidate sets for each empty cell
    candidates = [[set() for _ in range(9)] for _ in range(9)]
    for r in range(9):
        for c in range(9):
            if puzzle[r][c] == 0:
                cands = _get_candidates(puzzle, r, c)
                if len(cands) == 0:
                    return []  # Dead end: empty cell with no candidates
                candidates[r][c] = cands

    # Solve recursively, collecting solutions
    solutions = []
    _solve_recursive(puzzle, candidates, solutions, max_solutions)
    return solutions


def _get_candidates(grid, row, col):
    """Get all valid candidates for an empty cell."""
    used = set()

    # Row constraint
    for c in range(9):
        if grid[row][c] != 0:
            used.add(grid[row][c])

    # Column constraint
    for r in range(9):
        if grid[r][col] != 0:
            used.add(grid[r][col])

    # 3x3 box constraint
    box_r, box_c = (row // 3) * 3, (col // 3) * 3
    for r in range(box_r, box_r + 3):
        for c in range(box_c, box_c + 3):
            if grid[r][c] != 0:
                used.add(grid[r][c])

    return set(range(1, 10)) - used


def _propagate(grid, candidates):
    """
    Apply constraint propagation: naked singles and hidden singles.
    Modifies grid and candidates in place.

    Returns:
        True if consistent, False if a contradiction is found
    """
    changed = True
    while changed:
        changed = False

        # ── Naked Singles: cells with exactly one candidate ──
        for r in range(9):
            for c in range(9):
                if grid[r][c] != 0:
                    continue
                if len(candidates[r][c]) == 0:
                    return False  # Contradiction
                if len(candidates[r][c]) == 1:
                    val = next(iter(candidates[r][c]))
                    if not _place_value(grid, candidates, r, c, val):
                        return False
                    changed = True

        # ── Hidden Singles: value that can go in only one cell in a unit ──
        for val in range(1, 10):
            # Check each row
            for r in range(9):
                if any(grid[r][c] == val for c in range(9)):
                    continue  # Already placed in this row
                positions = [c for c in range(9)
                             if grid[r][c] == 0 and val in candidates[r][c]]
                if len(positions) == 0:
                    return False  # val must be in this row but can't be placed
                if len(positions) == 1:
                    c = positions[0]
                    if not _place_value(grid, candidates, r, c, val):
                        return False
                    changed = True

            # Check each column
            for c in range(9):
                if any(grid[r][c] == val for r in range(9)):
                    continue
                positions = [r for r in range(9)
                             if grid[r][c] == 0 and val in candidates[r][c]]
                if len(positions) == 0:
                    return False
                if len(positions) == 1:
                    r = positions[0]
                    if not _place_value(grid, candidates, r, c, val):
                        return False
                    changed = True

            # Check each 3x3 box
            for box_r in range(3):
                for box_c in range(3):
                    found = False
                    for dr in range(3):
                        for dc in range(3):
                            if grid[box_r * 3 + dr][box_c * 3 + dc] == val:
                                found = True
                    if found:
                        continue

                    positions = []
                    for dr in range(3):
                        for dc in range(3):
                            r, c = box_r * 3 + dr, box_c * 3 + dc
                            if grid[r][c] == 0 and val in candidates[r][c]:
                                positions.append((r, c))

                    if len(positions) == 0:
                        return False
                    if len(positions) == 1:
                        r, c = positions[0]
                        if not _place_value(grid, candidates, r, c, val):
                            return False
                        changed = True

    return True


def _place_value(grid, candidates, row, col, val):
    """
    Place a value in a cell and eliminate it from all peers' candidate sets.

    Returns:
        True if consistent, False if a contradiction is created
    """
    grid[row][col] = val
    candidates[row][col] = set()

    # Remove val from row peers
    for c in range(9):
        if c != col and val in candidates[row][c]:
            candidates[row][c].discard(val)
            if grid[row][c] == 0 and len(candidates[row][c]) == 0:
                return False

    # Remove val from column peers
    for r in range(9):
        if r != row and val in candidates[r][col]:
            candidates[r][col].discard(val)
            if grid[r][col] == 0 and len(candidates[r][col]) == 0:
                return False

    # Remove val from box peers
    box_r, box_c = (row // 3) * 3, (col // 3) * 3
    for r in range(box_r, box_r + 3):
        for c in range(box_c, box_c + 3):
            if (r != row or c != col) and val in candidates[r][c]:
                candidates[r][c].discard(val)
                if grid[r][c] == 0 and len(candidates[r][c]) == 0:
                    return False

    return True


def _solve_recursive(grid, candidates, solutions, max_solutions):
    """
    Recursive backtracking with MRV heuristic and constraint propagation.
    Collects solutions into the solutions list, up to max_solutions.
    """
    if len(solutions) >= max_solutions:
        return

    # Deep copy for this branch
    g = [row[:] for row in grid]
    c = [[cell.copy() for cell in row] for row in candidates]

    # Apply constraint propagation
    if not _propagate(g, c):
        return  # Contradiction in this branch

    # Find all remaining empty cells
    empty_cells = []
    for r in range(9):
        for col in range(9):
            if g[r][col] == 0:
                empty_cells.append((r, col, len(c[r][col])))

    # If no empty cells remain, we have a solution
    if not empty_cells:
        solutions.append([row[:] for row in g])
        return

    # MRV: pick the empty cell with fewest candidates
    empty_cells.sort(key=lambda x: x[2])
    best_r, best_c, best_count = empty_cells[0]

    if best_count == 0:
        return  # Dead end

    # Try each candidate value
    for val in sorted(c[best_r][best_c]):
        if len(solutions) >= max_solutions:
            return

        # Deep copy for this guess
        g2 = [row[:] for row in g]
        c2 = [[cell.copy() for cell in row] for row in c]

        # Place the value and propagate
        if _place_value(g2, c2, best_r, best_c, val):
            _solve_recursive(g2, c2, solutions, max_solutions)


def _is_valid_complete(grid):
    """
    Verify a completed grid satisfies every Sudoku constraint.
    Each row, column, and 3x3 box must contain exactly the digits 1-9.
    """
    target = set(range(1, 10))

    # Check rows
    for i in range(9):
        if set(grid[i]) != target:
            return False

    # Check columns
    for j in range(9):
        col_vals = {grid[i][j] for i in range(9)}
        if col_vals != target:
            return False

    # Check 3x3 boxes
    for box_r in range(3):
        for box_c in range(3):
            box_vals = set()
            for r in range(box_r * 3, box_r * 3 + 3):
                for c in range(box_c * 3, box_c * 3 + 3):
                    box_vals.add(grid[r][c])
            if box_vals != target:
                return False

    return True
