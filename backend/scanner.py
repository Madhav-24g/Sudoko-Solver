"""
scanner.py — Template-Optimized Sudoku Scanner

Specifically optimized for the "Sudoku Master" mobile app template.
Uses computer vision techniques tailored to the fixed template:
- Parchment/beige background
- Brown/tan digit tiles with white digits
- Light beige empty cells
- Thick dark grid lines separating 3x3 boxes

Processing Pipeline:
1. Grid Detection — Find the 9x9 grid via contour analysis
2. Perspective Correction — Warp to a perfect square
3. Cell Segmentation — Divide into 81 cells with margin cropping
4. Cell Classification — Filled vs empty via intensity analysis
5. Digit Extraction — Isolate white digits from brown background
6. Digit Recognition — Structural feature analysis + template matching
7. Confidence Scoring — Per-cell confidence for user review
8. Template Caching — Save verified digits for future high-accuracy matching
"""

import os
import json
import uuid
import shutil
import tempfile
import cv2
import numpy as np
from pathlib import Path


# Directory to cache learned digit templates (persisted on purpose — kept inside the project)
TEMPLATE_DIR = Path(__file__).parent / 'digit_templates'
# Temporary storage for scan cell images (for template learning).
# IMPORTANT: lives outside the project folder. Flask's debug-mode
# auto-reloader watches the project directory for changes; writing new
# files into a subfolder of the project during a request makes it think
# source code changed, triggers a restart, and kills the in-flight
# request — which the browser shows as a failed/dropped connection.
SCAN_CACHE_DIR = Path(tempfile.gettempdir()) / 'sudoku_scan_cache'


class SudokuScanner:
    """Template-optimized Sudoku scanner for the Sudoku Master app."""

    def __init__(self):
        self.digit_templates = {}  # {digit: [list of template images]}
        self._load_templates()

    # ── Public API ───────────────────────────────────────────────────────────

    def scan(self, image_bytes):
        """
        Scan a Sudoku puzzle from an image.

        Args:
            image_bytes: Raw image bytes (JPEG/PNG)

        Returns:
            dict with: success, grid, confidence, scan_id, message
        """
        # Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return {
                'success': False,
                'engine': None,
                'grid': None,
                'confidence': None,
                'scan_id': None,
                'message': 'Could not decode image. Please provide a valid JPEG or PNG.'
            }

        # Find and extract the grid
        grid_img = self._find_and_extract_grid(img)
        if grid_img is None:
            return {
                'success': False,
                'engine': None,
                'grid': None,
                'confidence': None,
                'scan_id': None,
                'message': 'Could not detect the Sudoku grid. Please ensure the full 9×9 grid is visible.'
            }

        # Extract individual cells
        cell_images = self._extract_cells(grid_img)

        # Classify and recognize each cell
        grid = [[0] * 9 for _ in range(9)]
        confidence = [[0.0] * 9 for _ in range(9)]

        for r in range(9):
            for c in range(9):
                cell_img = cell_images[r][c]
                is_filled = self._is_cell_filled(cell_img)

                if is_filled:
                    digit, conf = self._recognize_digit(cell_img)
                    grid[r][c] = digit
                    confidence[r][c] = round(conf, 3)
                else:
                    grid[r][c] = 0
                    confidence[r][c] = 0.95  # High confidence it's empty

        # Cache cell images for template learning
        scan_id = str(uuid.uuid4())[:8]
        self._cache_scan_cells(scan_id, cell_images, grid)

        # IMPORTANT: cv2/numpy operations (e.g. cv2.matchTemplate) return
        # numpy scalar types like float32/int32. Flask's jsonify() can only
        # serialize native Python types, so coerce everything here —
        # otherwise this throws "Object of type float32 is not JSON
        # serializable" deep inside the response, which surfaces to the
        # user as a generic scan failure.
        grid = [[int(v) for v in row] for row in grid]
        confidence = [[float(v) for v in row] for row in confidence]

        return {
            'success': True,
            'engine': 'opencv_fallback',
            'grid': grid,
            'confidence': confidence,
            'scan_id': scan_id,
            'message': 'Scan complete. Please verify the detected digits.'
        }

    def save_verified_templates(self, scan_id, verified_grid):
        """
        Save verified digit images as templates for future recognition.
        Called after user confirms the scan result.

        Args:
            scan_id: ID from the scan response
            verified_grid: 9x9 grid with user-corrected digits

        Returns:
            bool: True if templates were saved successfully
        """
        cache_dir = SCAN_CACHE_DIR / scan_id
        if not cache_dir.exists():
            return False

        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        saved_count = 0

        for r in range(9):
            for c in range(9):
                digit = verified_grid[r][c]
                if digit == 0:
                    continue

                # Load the cached cell image
                cell_path = cache_dir / f'cell_{r}_{c}.png'
                if not cell_path.exists():
                    continue

                cell_img = cv2.imread(str(cell_path))
                if cell_img is None:
                    continue

                # Extract the digit region
                digit_img = self._extract_digit_image(cell_img)
                if digit_img is None:
                    continue

                # Save template
                digit_dir = TEMPLATE_DIR / str(digit)
                digit_dir.mkdir(parents=True, exist_ok=True)

                # Keep up to 5 templates per digit (best examples)
                existing = list(digit_dir.glob('*.png'))
                template_path = digit_dir / f'{len(existing)}.png'
                cv2.imwrite(str(template_path), digit_img)
                saved_count += 1

        # Reload templates
        self._load_templates()

        # Clean up scan cache
        self._cleanup_scan_cache(scan_id)

        return saved_count > 0

    # ── Grid Detection ───────────────────────────────────────────────────────

    def _find_and_extract_grid(self, img):
        """
        Detect the Sudoku grid and return a perspective-corrected square image.
        Tailored for the screenshot layout (with cell aggregator & Y-clustering)
        with standard contour search as fallback.
        """
        h, w = img.shape[:2]
        
        # ── 1. Cell Aggregator Strategy (Primary for screenshots) ──
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV, 11, 2
            )
            
            contours, _ = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            
            cell_coords = []
            for cnt in contours:
                x, y, cw, cb_h = cv2.boundingRect(cnt)
                aspect = cw / cb_h
                min_size = int(w * 0.07)
                max_size = int(w * 0.13)
                
                # Check for cell-like shapes (aspect ratio ~ 1.0)
                if min_size <= cw <= max_size and min_size <= cb_h <= max_size and 0.82 <= aspect <= 1.18:
                    cx = x + cw // 2
                    cy = y + cb_h // 2
                    # Filter out coordinates in top 10% and bottom 15% (logo/ads/header/footer)
                    if 0.1 * h < cy < 0.85 * h:
                        cell_coords.append((x, y, x + cw, y + cb_h, cx, cy))
            
            if len(cell_coords) >= 15:
                # Group cells by Y coordinate to find row clusters
                cell_coords.sort(key=lambda c: c[5])
                
                y_clusters = []
                for cell in cell_coords:
                    cy = cell[5]
                    added = False
                    for cluster in y_clusters:
                        # Cluster together if centers are within 15 pixels
                        if abs(cy - np.mean([c[5] for c in cluster])) < 15:
                            cluster.append(cell)
                            added = True
                            break
                    if not added:
                        y_clusters.append([cell])
                
                # Sort clusters by their average Y coordinate
                y_clusters.sort(key=lambda cluster: np.mean([c[5] for c in cluster]))
                
                # Look for 9 consecutive clusters with regular gaps (approx 40-90px)
                board_clusters = []
                for i in range(len(y_clusters) - 8):
                    candidate_seq = y_clusters[i:i+9]
                    valid = True
                    gaps = []
                    for j in range(8):
                        y_curr = np.mean([c[5] for c in candidate_seq[j]])
                        y_next = np.mean([c[5] for c in candidate_seq[j+1]])
                        gap = y_next - y_curr
                        gaps.append(gap)
                        if not (35 <= gap <= 95):
                            valid = False
                            break
                    if valid:
                        # Std dev of gaps must be small (uniform row spacing)
                        if np.std(gaps) < 10:
                            board_clusters = candidate_seq
                            break
                
                # Fallback: if no perfect 9-sequence spacing found but we have enough clusters, take top 9
                if not board_clusters and len(y_clusters) >= 9:
                    board_clusters = y_clusters[:9]
                
                if board_clusters:
                    board_cells = []
                    for cluster in board_clusters:
                        board_cells.extend(cluster)
                    
                    xs1 = [c[0] for c in board_cells]
                    ys1 = [c[1] for c in board_cells]
                    xs2 = [c[2] for c in board_cells]
                    ys2 = [c[3] for c in board_cells]
                    
                    grid_x1 = min(xs1)
                    grid_y1 = min(ys1)
                    grid_x2 = max(xs2)
                    grid_y2 = max(ys2)
                    
                    # Make it a perfect square
                    gw = grid_x2 - grid_x1
                    gh = grid_y2 - grid_y1
                    side = max(gw, gh)
                    
                    center_x = grid_x1 + gw / 2
                    center_y = grid_y1 + gh / 2
                    
                    grid_x1 = int(center_x - side / 2)
                    grid_x2 = int(center_x + side / 2)
                    grid_y1 = int(center_y - side / 2)
                    grid_y2 = int(center_y + side / 2)
                    
                    # Ensure boundaries are inside image frame
                    grid_x1 = max(0, grid_x1)
                    grid_y1 = max(0, grid_y1)
                    grid_x2 = min(w - 1, grid_x2)
                    grid_y2 = min(h - 1, grid_y2)
                    
                    # Warp to square
                    side_dst = 450
                    src_pts = np.array([
                        [grid_x1, grid_y1],
                        [grid_x2, grid_y1],
                        [grid_x2, grid_y2],
                        [grid_x1, grid_y2]
                    ], dtype=np.float32)
                    
                    dst_pts = np.array([
                        [0, 0],
                        [side_dst - 1, 0],
                        [side_dst - 1, side_dst - 1],
                        [0, side_dst - 1]
                    ], dtype=np.float32)
                    
                    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
                    warped = cv2.warpPerspective(img, M, (side_dst, side_dst))
                    return warped
        except Exception as e:
            print(f"Warning: Cell aggregator grid extraction failed: {e}. Falling back to contours.")
            
        # ── 2. Standard Contour Fallback Strategy (For generic photos/skewed views) ──
        result = self._detect_grid_contour(img)
        if result is not None:
            return result

        result = self._detect_grid_adaptive(img)
        if result is not None:
            return result

        return None

    def _detect_grid_contour(self, img):
        """Detect grid using contour analysis."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)

        # Adaptive threshold to highlight grid lines
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2
        )

        # Dilate to connect broken lines
        kernel = np.ones((3, 3), np.uint8)
        thresh = cv2.dilate(thresh, kernel, iterations=1)

        # Find contours
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if not contours:
            return None

        # Sort by area, largest first
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        img_area = img.shape[0] * img.shape[1]

        for contour in contours[:5]:  # Check top 5 largest contours
            area = cv2.contourArea(contour)
            if area < 0.05 * img_area:
                continue  # Too small

            # Approximate to polygon
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

            # Accept quadrilaterals (4 vertices)
            if len(approx) == 4:
                return self._warp_grid(img, approx.reshape(4, 2))

        # If no quadrilateral found, try with looser approximation
        for contour in contours[:5]:
            area = cv2.contourArea(contour)
            if area < 0.05 * img_area:
                continue

            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.05 * peri, True)

            if len(approx) == 4:
                return self._warp_grid(img, approx.reshape(4, 2))

        return None

    def _detect_grid_adaptive(self, img):
        """Fallback grid detection with different preprocessing."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Try Canny edge detection
        edges = cv2.Canny(gray, 50, 150)
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=2)

        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if not contours:
            return None

        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        img_area = img.shape[0] * img.shape[1]

        for contour in contours[:5]:
            area = cv2.contourArea(contour)
            if area < 0.05 * img_area:
                continue

            peri = cv2.arcLength(contour, True)

            # Try multiple epsilon values for approxPolyDP
            for eps_mult in [0.01, 0.02, 0.03, 0.05, 0.08]:
                approx = cv2.approxPolyDP(contour, eps_mult * peri, True)
                if len(approx) == 4:
                    return self._warp_grid(img, approx.reshape(4, 2))

        # Last resort: use bounding rectangle of largest contour
        if contours:
            largest = contours[0]
            area = cv2.contourArea(largest)
            if area > 0.05 * img_area:
                rect = cv2.minAreaRect(largest)
                box = cv2.boxPoints(rect)
                return self._warp_grid(img, box.astype(np.float32))

        return None

    def _warp_grid(self, img, pts):
        """Apply perspective transform to extract a square grid image."""
        # Order points: top-left, top-right, bottom-right, bottom-left
        ordered = self._order_points(pts)

        # Calculate output side length
        widths = [
            np.linalg.norm(ordered[0] - ordered[1]),
            np.linalg.norm(ordered[2] - ordered[3])
        ]
        heights = [
            np.linalg.norm(ordered[0] - ordered[3]),
            np.linalg.norm(ordered[1] - ordered[2])
        ]
        side = int(max(max(widths), max(heights)))
        side = max(side, 270)  # Minimum 270px (30px per cell)

        dst = np.array([
            [0, 0],
            [side - 1, 0],
            [side - 1, side - 1],
            [0, side - 1]
        ], dtype=np.float32)

        M = cv2.getPerspectiveTransform(ordered.astype(np.float32), dst)
        warped = cv2.warpPerspective(img, M, (side, side))

        return warped

    def _order_points(self, pts):
        """Order 4 points as: top-left, top-right, bottom-right, bottom-left."""
        pts = pts.astype(np.float32)
        rect = np.zeros((4, 2), dtype=np.float32)

        # Top-left has smallest x+y, bottom-right has largest x+y
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]

        # Top-right has smallest y-x, bottom-left has largest y-x
        d = np.diff(pts, axis=1).flatten()
        rect[1] = pts[np.argmin(d)]
        rect[3] = pts[np.argmax(d)]

        return rect

    # ── Cell Segmentation ────────────────────────────────────────────────────

    def _extract_cells(self, grid_img):
        """
        Divide the warped grid image into 81 individual cell images.
        Applies margin cropping to exclude grid lines.
        """
        side = grid_img.shape[0]
        cell_size = side / 9.0

        cells = []
        for r in range(9):
            row_cells = []
            for c in range(9):
                y1 = int(r * cell_size)
                y2 = int((r + 1) * cell_size)
                x1 = int(c * cell_size)
                x2 = int((c + 1) * cell_size)

                cell = grid_img[y1:y2, x1:x2]

                # Crop margins to exclude grid lines (12% on each side)
                ch, cw = cell.shape[:2]
                margin_y = int(ch * 0.12)
                margin_x = int(cw * 0.12)
                cell = cell[margin_y:ch - margin_y, margin_x:cw - margin_x]

                row_cells.append(cell)
            cells.append(row_cells)

        return cells

    # ── Cell Classification ──────────────────────────────────────────────────

    def _is_cell_filled(self, cell_img):
        """
        Determine if a cell contains a digit (brown tile) or is empty (light beige).

        Uses intensity analysis: brown tiles are significantly darker than
        empty cells in the Sudoku Master template.
        """
        if cell_img is None or cell_img.size == 0:
            return False

        gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Analyze the center region (inner 60%) to avoid edge artifacts
        cy1, cy2 = h // 5, 4 * h // 5
        cx1, cx2 = w // 5, 4 * w // 5
        center = gray[cy1:cy2, cx1:cx2]

        if center.size == 0:
            return False

        mean_intensity = np.mean(center)
        std_intensity = np.std(center)

        # Brown cells: mean ~100-170, std higher (due to white digit)
        # Empty cells: mean ~190-240, std low (uniform light background)
        # The combined check of mean and std improves reliability
        if mean_intensity < 180 and std_intensity > 15:
            return True
        if mean_intensity < 160:
            return True

        return False

    # ── Digit Extraction ─────────────────────────────────────────────────────

    def _extract_digit_image(self, cell_img):
        """
        Extract a clean binary digit image from a filled cell.
        The digit is white on brown background in the Sudoku Master template.
        """
        gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)

        # Apply CLAHE for contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        enhanced = clahe.apply(gray)

        # Threshold to isolate bright digit from dark background
        # Use Otsu's method for automatic threshold selection
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # If Otsu gives poor results, try fixed threshold
        white_ratio = np.sum(binary > 0) / binary.size
        if white_ratio > 0.65 or white_ratio < 0.05:
            _, binary = cv2.threshold(enhanced, 170, 255, cv2.THRESH_BINARY)

        # Clean up noise with morphological operations
        kernel_small = np.ones((2, 2), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_small)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel_small)

        # Find the digit contour (largest white region)
        contours, _ = cv2.findContours(
            binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if not contours:
            return None

        # Find the largest contour that is likely the digit
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)

        # Filter: digit should occupy at least 5% of the cell
        if area < binary.size * 0.03:
            return None

        # Get bounding box
        x, y, w, h = cv2.boundingRect(largest)

        # Extract digit with a small padding
        pad = 3
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(binary.shape[1], x + w + pad)
        y2 = min(binary.shape[0], y + h + pad)
        digit_crop = binary[y1:y2, x1:x2]

        if digit_crop.size == 0:
            return None

        # Resize to standard size (28x20) preserving aspect ratio
        target_h, target_w = 28, 20
        dh, dw = digit_crop.shape
        scale = min(target_h / dh, target_w / dw) * 0.85
        new_h, new_w = max(1, int(dh * scale)), max(1, int(dw * scale))
        resized = cv2.resize(digit_crop, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Center in a target_h x target_w canvas
        canvas = np.zeros((target_h, target_w), dtype=np.uint8)
        y_off = (target_h - new_h) // 2
        x_off = (target_w - new_w) // 2
        canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized

        return canvas

    # ── Digit Recognition ────────────────────────────────────────────────────

    def _recognize_digit(self, cell_img):
        """
        Recognize the digit in a filled cell.

        Strategy:
        1. If templates available → template matching (highest accuracy)
        2. Fallback → structural feature classification

        Returns:
            (digit, confidence) where digit is 1-9, confidence is 0.0-1.0
        """
        digit_img = self._extract_digit_image(cell_img)

        if digit_img is None:
            return 0, 0.0

        # Try template matching first (if we have cached templates)
        if self.digit_templates:
            digit, conf = self._template_match(digit_img)
            if conf > 0.5:
                return digit, conf

        # Fall back to structural feature analysis
        return self._structural_classify(digit_img, cell_img)

    def _template_match(self, digit_img):
        """
        Match digit against cached templates using normalized cross-correlation.
        Returns (digit, confidence).
        """
        best_digit = 0
        best_score = -1.0

        for digit, templates in self.digit_templates.items():
            for template in templates:
                # Ensure same size
                if template.shape != digit_img.shape:
                    template = cv2.resize(template, (digit_img.shape[1], digit_img.shape[0]))

                # Normalized cross-correlation
                result = cv2.matchTemplate(
                    digit_img, template, cv2.TM_CCOEFF_NORMED
                )
                score = result[0][0] if result.size > 0 else 0.0

                if score > best_score:
                    best_score = score
                    best_digit = digit

        # Convert match score to confidence
        confidence = max(0.0, min(1.0, (best_score + 1.0) / 2.0))

        return best_digit, confidence

    def _structural_classify(self, digit_img, cell_img):
        """
        Classify digit using structural features when templates are unavailable.

        Features used:
        1. Number of holes (internal contours)
        2. Aspect ratio of bounding box
        3. Pixel density distribution (vertical/horizontal thirds)
        4. Horizontal transition counts at different heights
        5. Symmetry analysis

        Returns:
            (digit, confidence)
        """
        if digit_img is None or digit_img.size == 0:
            return 0, 0.0

        h, w = digit_img.shape
        total_white = np.sum(digit_img > 0)

        if total_white < 10:
            return 0, 0.0

        # ── Feature: Holes (internal contours) ──
        contours, hierarchy = cv2.findContours(
            digit_img, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        holes = 0
        if hierarchy is not None and len(hierarchy) > 0:
            for i in range(len(hierarchy[0])):
                # A contour with a parent is an internal hole
                if hierarchy[0][i][3] != -1:
                    area = cv2.contourArea(contours[i])
                    if area > 8:  # Filter tiny noise holes
                        holes += 1

        # ── Feature: Aspect ratio ──
        # Find overall bounding box of white pixels
        coords = np.column_stack(np.where(digit_img > 0))
        if coords.size == 0:
            return 0, 0.0
        min_y, min_x = coords.min(axis=0)
        max_y, max_x = coords.max(axis=0)
        bbox_h = max(max_y - min_y + 1, 1)
        bbox_w = max(max_x - min_x + 1, 1)
        aspect_ratio = bbox_w / bbox_h

        # ── Feature: Pixel density ──
        density = total_white / (h * w)

        # ── Feature: Vertical distribution (top/mid/bottom thirds) ──
        third_h = max(h // 3, 1)
        top_px = np.sum(digit_img[:third_h] > 0) / max(total_white, 1)
        mid_px = np.sum(digit_img[third_h:2 * third_h] > 0) / max(total_white, 1)
        bot_px = np.sum(digit_img[2 * third_h:] > 0) / max(total_white, 1)

        # ── Feature: Horizontal distribution (left/right halves) ──
        half_w = max(w // 2, 1)
        left_px = np.sum(digit_img[:, :half_w] > 0) / max(total_white, 1)
        right_px = np.sum(digit_img[:, half_w:] > 0) / max(total_white, 1)

        # ── Feature: Horizontal transitions at key heights ──
        cross_25 = self._count_transitions(digit_img[h // 4])
        cross_50 = self._count_transitions(digit_img[h // 2])
        cross_75 = self._count_transitions(digit_img[3 * h // 4])

        # ── Feature: Top-half vs bottom-half hole detection ──
        top_half = digit_img[:h // 2]
        bot_half = digit_img[h // 2:]
        top_holes = self._count_holes_in_region(top_half)
        bot_holes = self._count_holes_in_region(bot_half)

        # ── Feature: Vertical symmetry ──
        flipped_v = cv2.flip(digit_img, 1)
        v_symmetry = np.sum(digit_img == flipped_v) / digit_img.size

        # ── Decision Tree Classification ──
        base_conf = 0.82

        # === 8: Two holes (figure-eight shape) ===
        if holes >= 2:
            return 8, 0.92

        # === 1: Very narrow digit ===
        if aspect_ratio < 0.32 and density < 0.35:
            return 1, 0.92

        # === Digits with 1 hole: 0, 4, 6, 9 ===
        if holes == 1:
            # 0 doesn't appear in Sudoku, so it's 4, 6, or 9

            # 9: hole in top half, tail extends down
            if top_holes >= 1 and bot_holes == 0:
                return 9, 0.88

            # 6: hole in bottom half, curve extends up
            if bot_holes >= 1 and top_holes == 0:
                return 6, 0.88

            # 4: angular, often has hole in upper portion,
            # distinguished from 9 by being more angular/left-heavy at top
            if top_holes >= 1:
                # Check if more angular (4) vs curved (9)
                # 4 tends to have more weight on the right side
                if right_px > 0.55:
                    return 4, 0.80
                return 9, 0.78

            if bot_holes >= 1:
                return 6, 0.80

            # Ambiguous hole position
            if top_px > bot_px:
                return 9, 0.72
            else:
                return 6, 0.72

        # === Digits with 0 holes: 1, 2, 3, 5, 7 ===
        # (1 already handled above by aspect ratio)

        # Additional check for 1: even if aspect ratio is borderline
        if aspect_ratio < 0.38 and density < 0.30:
            return 1, 0.85

        # 7: Very top-heavy — most pixels in top third, diagonal going down
        if top_px > 0.45 and bot_px < 0.28:
            return 7, 0.88

        # 4 without a closed hole (open-top 4)
        if cross_50 >= 2 and right_px > 0.52 and top_px < bot_px:
            # 4 has a strong horizontal crossing at mid-height
            return 4, base_conf

        # 3: Right-heavy with two bumps (top and bottom curves)
        # 3 has more weight on the right side
        if right_px > 0.58 and cross_50 >= 1:
            return 3, base_conf

        # 2 vs 5: Both have no holes, similar density
        # 2: top curve goes right, bottom horizontal goes left-to-right
        # 5: top horizontal, bottom curve goes right

        # 5: Top is wider/heavier on the left, bottom curves right
        if top_px > 0.35 and left_px > 0.50:
            return 5, 0.78

        # 2: Bottom is heavier, top curve
        if bot_px > 0.35 and right_px > 0.45:
            return 2, 0.78

        # 3: default for right-heavy zero-hole digits
        if right_px > 0.52:
            return 3, 0.72

        # 5: default for left-heavy zero-hole digits
        if left_px > 0.52:
            return 5, 0.72

        # Last resort: use projection analysis
        return self._projection_classify(digit_img, base_conf * 0.85)

    def _projection_classify(self, digit_img, max_conf):
        """
        Fallback classifier using horizontal and vertical projections.
        Analyzes the density profile of the digit.
        """
        h, w = digit_img.shape

        # Horizontal projection (sum of white pixels per row)
        h_proj = np.sum(digit_img > 0, axis=1).astype(float)
        if np.max(h_proj) > 0:
            h_proj = h_proj / np.max(h_proj)

        # Vertical projection (sum of white pixels per column)
        v_proj = np.sum(digit_img > 0, axis=0).astype(float)
        if np.max(v_proj) > 0:
            v_proj = v_proj / np.max(v_proj)

        # Find peak positions in horizontal projection
        h_peaks = []
        for i in range(1, len(h_proj) - 1):
            if h_proj[i] > h_proj[i - 1] and h_proj[i] > h_proj[i + 1]:
                if h_proj[i] > 0.5:
                    h_peaks.append(i / h)

        # 2: peak at top and flat bottom
        if len(h_peaks) >= 1 and h_peaks[0] < 0.3 and h_proj[-1] > 0.5:
            return 2, max_conf

        # 7: strong peak at very top, decreasing
        if len(h_peaks) >= 1 and h_peaks[0] < 0.15:
            return 7, max_conf

        # 3: peaks at top and bottom (two bumps)
        if len(h_peaks) >= 2:
            return 3, max_conf

        # 5: peak at top-ish
        if len(h_peaks) >= 1 and h_peaks[0] < 0.4:
            return 5, max_conf

        # Default guess
        return 2, max_conf * 0.7

    # ── Helper Functions ─────────────────────────────────────────────────────

    def _count_transitions(self, row):
        """Count background-to-foreground transitions in a pixel row."""
        transitions = 0
        in_white = False
        for pixel in row:
            if pixel > 0 and not in_white:
                transitions += 1
                in_white = True
            elif pixel == 0:
                in_white = False
        return transitions

    def _count_holes_in_region(self, region):
        """Count internal contour holes in a sub-region of the digit."""
        if region is None or region.size == 0:
            return 0

        contours, hierarchy = cv2.findContours(
            region.copy(), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        if hierarchy is None or len(hierarchy) == 0:
            return 0

        holes = 0
        for i in range(len(hierarchy[0])):
            if hierarchy[0][i][3] != -1:
                area = cv2.contourArea(contours[i])
                if area > 5:
                    holes += 1
        return holes

    # ── Template Management ──────────────────────────────────────────────────

    def _load_templates(self):
        """Load cached digit templates from disk."""
        self.digit_templates = {}

        if not TEMPLATE_DIR.exists():
            return

        for digit_dir in TEMPLATE_DIR.iterdir():
            if digit_dir.is_dir():
                try:
                    digit = int(digit_dir.name)
                except ValueError:
                    continue

                templates = []
                for img_path in sorted(digit_dir.glob('*.png'))[:5]:
                    img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
                    if img is not None:
                        templates.append(img)

                if templates:
                    self.digit_templates[digit] = templates

    def _save_templates_to_disk(self):
        """Save current templates to disk."""
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

        for digit, templates in self.digit_templates.items():
            digit_dir = TEMPLATE_DIR / str(digit)
            digit_dir.mkdir(parents=True, exist_ok=True)

            for i, template in enumerate(templates[:5]):
                path = digit_dir / f'{i}.png'
                cv2.imwrite(str(path), template)

    def _cache_scan_cells(self, scan_id, cell_images, grid):
        """Cache cell images from a scan for potential template learning."""
        cache_dir = SCAN_CACHE_DIR / scan_id
        cache_dir.mkdir(parents=True, exist_ok=True)

        for r in range(9):
            for c in range(9):
                if grid[r][c] != 0:  # Only cache filled cells
                    path = cache_dir / f'cell_{r}_{c}.png'
                    cv2.imwrite(str(path), cell_images[r][c])

        # Save grid as JSON for reference
        meta_path = cache_dir / 'grid.json'
        with open(meta_path, 'w') as f:
            json.dump({'grid': grid}, f)

    def _cleanup_scan_cache(self, scan_id):
        """Remove cached scan data after templates are saved."""
        cache_dir = SCAN_CACHE_DIR / scan_id
        if cache_dir.exists():
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)

    def cleanup_old_caches(self, max_age_hours=24):
        """Remove scan caches older than max_age_hours."""
        import time
        if not SCAN_CACHE_DIR.exists():
            return

        cutoff = time.time() - (max_age_hours * 3600)
        for d in SCAN_CACHE_DIR.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                import shutil
                shutil.rmtree(d, ignore_errors=True)
