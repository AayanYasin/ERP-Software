
import matplotlib.pyplot as plt
from fractions import Fraction
from math import ceil
from itertools import combinations, product
import time

# ========== UTILITY FUNCTIONS ==========

def parse_inches(value: str) -> float:
    value = value.strip()
    try:
        if ' ' in value:
            whole, frac = value.split(' ')
            num, denom = frac.split('/')
            return int(whole) + int(num) / int(denom)
        elif '/' in value:
            num, denom = value.split('/')
            return int(num) / int(denom)
        return float(value)
    except Exception:
        return 0.0

def to_mixed_fraction(value):
    inches = int(value)
    fraction = Fraction(value - inches).limit_denominator(16)
    if fraction == 0:
        return f"{inches}"
    return f"{inches} {fraction.numerator}/{fraction.denominator}"

# ========== WASTE SCANNING ==========

def scan_waste_blocks(sheet_w, sheet_h, rects, resolution=8):
    grid_w = int(sheet_w * resolution)
    grid_h = int(sheet_h * resolution)
    used = [[False for _ in range(grid_w)] for _ in range(grid_h)]

    for x, y, w, h, *_ in rects:
        for dx in range(ceil(w * resolution)):
            for dy in range(ceil(h * resolution)):
                px = int((x * resolution) + dx)
                py = int((y * resolution) + dy)
                if 0 <= px < grid_w and 0 <= py < grid_h:
                    used[py][px] = True

    visited = [[False for _ in range(grid_w)] for _ in range(grid_h)]
    waste_blocks = []

    for y in range(grid_h - 1, -1, -1):
        for x in range(grid_w):
            if not used[y][x] and not visited[y][x]:
                max_w = 0
                while x + max_w < grid_w and not used[y][x + max_w] and not visited[y][x + max_w]:
                    max_w += 1

                max_h = 1
                while True:
                    next_y = y - max_h
                    if next_y < 0:
                        break
                    if any(used[next_y][x + dx] or visited[next_y][x + dx] for dx in range(max_w)):
                        break
                    max_h += 1

                for dy in range(max_h):
                    for dx in range(max_w):
                        visited[y - dy][x + dx] = True

                top_y = y - max_h + 1
                waste_blocks.append((x / resolution, top_y / resolution, max_w / resolution, max_h / resolution))
    return waste_blocks

# ========== FALLBACK OPTIMIZER ==========

def optimize_layout(sheet_w, sheet_h, cuts):
    def find_best_row(pieces, max_width):
        best_combo = []
        best_total = 0.0
        for r in range(1, len(pieces) + 1):
            for combo in combinations(pieces, r):
                for orientation in product([0, 1], repeat=len(combo)):
                    total = 0.0
                    row = []
                    valid = True
                    for i, p in enumerate(combo):
                        w, h, label, is_bracket = p
                        if orientation[i] == 1:
                            w, h = h, w
                        if total + w > max_width:
                            valid = False
                            break
                        row.append((w, h, label, is_bracket))
                        total += w
                    if valid and total > best_total:
                        best_total = total
                        best_combo = (combo, row)
        return best_combo

    parsed = [tuple(cut) for cut in cuts]
    y_cursor = 0
    layout = []

    while parsed:
        result = find_best_row(parsed, sheet_w)
        if not result:
            break
        used_items, row = result
        row_height = max(h for _, h, _, _ in row)
        if y_cursor + row_height > sheet_h:
            break
        layout.extend(row)
        for item in used_items:
            parsed.remove(item)
        y_cursor += row_height

    return layout

# ========== RECTANGLE PLACEMENT ==========

def place_rectangles(sheet_w, sheet_h, rectangles, fallback_allowed=True):
    used = []
    current_y = 0
    row_height = 0
    current_x = 0
    scan_resolution = 8

    unplaced = []

    for rect in rectangles:
        w, h, label, is_bracket = rect
        placed = False

        # 1. Row-wise
        if current_x + w <= sheet_w and current_y + h <= sheet_h:
            used.append((current_x, current_y, w, h, label, is_bracket))
            current_x += w
            row_height = max(row_height, h)
            placed = True

        # 2. New row
        if not placed:
            new_y = current_y + row_height
            if new_y + h <= sheet_h:
                current_y = new_y
                current_x = 0
                row_height = h
                used.append((current_x, current_y, w, h, label, is_bracket))
                current_x += w
                placed = True

        # 3. Waste block reuse
        if not placed:
            waste_blocks = scan_waste_blocks(sheet_w, sheet_h, used)
            for wx, wy, ww, wh in waste_blocks:
                if w <= ww and h <= wh:
                    used.append((wx, wy, w, h, label, is_bracket))
                    placed = True
                    break
                elif h <= ww and w <= wh:
                    used.append((wx, wy, h, w, label, is_bracket))
                    placed = True
                    break

        # 4. Grid scan
        if not placed:
            grid_w = int(sheet_w * scan_resolution)
            grid_h = int(sheet_h * scan_resolution)
            grid = [[False for _ in range(grid_w)] for _ in range(grid_h)]

            for ux, uy, uw, uh, *_ in used:
                for dx in range(int(uw * scan_resolution)):
                    for dy in range(int(uh * scan_resolution)):
                        gx = int((ux + dx / scan_resolution) * scan_resolution)
                        gy = int((uy + dy / scan_resolution) * scan_resolution)
                        if 0 <= gx < grid_w and 0 <= gy < grid_h:
                            grid[gy][gx] = True

            for gy in range(grid_h):
                for gx in range(grid_w):
                    x_pos = gx / scan_resolution
                    y_pos = gy / scan_resolution

                    if x_pos + w > sheet_w or y_pos + h > sheet_h:
                        continue

                    fits = True
                    for dy in range(int(h * scan_resolution)):
                        for dx in range(int(w * scan_resolution)):
                            cx = gx + dx
                            cy = gy + dy
                            if cx >= grid_w or cy >= grid_h or grid[cy][cx]:
                                fits = False
                                break
                        if not fits:
                            break

                    if fits:
                        used.append((x_pos, y_pos, w, h, label, is_bracket))
                        placed = True
                        break
                if placed:
                    break

        # 5. Fallback optimizer
        if not placed and fallback_allowed:
            optimized = optimize_layout(sheet_w, sheet_h, rectangles)
            return place_rectangles(sheet_w, sheet_h, optimized, fallback_allowed=False)

        if not placed:
            unplaced.append(label)

    return used

# ========== VISUALIZATION ==========

def visualize(sheet_w, sheet_h, placed_rects):
    fig, ax = plt.subplots(figsize=(sheet_w / 6, sheet_h / 6))
    ax.set_xlim(0, sheet_w)
    ax.set_ylim(0, sheet_h)
    ax.set_aspect('equal')
    ax.set_title(f"Sheet Layout: {int(sheet_w)} x {int(sheet_h)} inches")
    ax.set_xlabel("Width (inches)")
    ax.set_ylabel("Height (inches)")

    for rect in placed_rects:
        x, y, w, h, label, is_bracket = rect
        ax.add_patch(plt.Rectangle((x, y), w, h, fill=True, edgecolor='black', facecolor='skyblue'))
        ax.text(x + w / 2, y + h / 2, label, ha='center', va='center', fontsize=6)
        if is_bracket:
            ax.plot([x, x + w], [y, y + h], 'r--', linewidth=1)

    for x, y, w, h in scan_waste_blocks(sheet_w, sheet_h, placed_rects):
        ax.add_patch(plt.Rectangle((x, y), w, h, fill=False, edgecolor='red', linestyle='--'))
        ax.text(x + w / 2, y + h / 2, f"{to_mixed_fraction(w)} x {to_mixed_fraction(h)}",
                ha='center', va='center', fontsize=5, color='red')

    plt.tight_layout()
    plt.show()

# ========== MAIN ==========

if __name__ == "__main__":
    time.time
    # SHEET_WIDTH = 48.0
    # SHEET_HEIGHT = 96.0

    # raw_pieces = [
    #     ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False),
    #     ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False),
    #     ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False),
    #     ("12", "31 3/8", False), ("12", "31 3/8", False), ("12", "31 3/8", False)
    # ]
    
    # SHEET_WIDTH = 48.0
    # SHEET_HEIGHT = 96.0

    # raw_pieces = [
    #     ("9", "40 3/8", False), ("9", "40 3/8", False), ("9", "40 3/8", False), ("9", "40 3/8", False),
    #     ("9", "40 3/8", False), ("9", "40 3/8", False), ("9", "40 3/8", False), ("9", "40 3/8", False),
    #     ("12", "40 3/8", False), ("12", "40 3/8", False), ("12", "46 3/8", False)
    # ]
    
    SHEET_WIDTH = 48.0
    SHEET_HEIGHT = 96.0

    
    raw_pieces = [
        ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
        ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
        ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
        ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
        ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
        ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
        ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
        ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
        ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
        ("4 1/2", "13 1/2", False), ("4 1/2", "13 1/2", False),
        ("19 1/2", "6 1/2", False), ("19 1/2", "6 1/2", False), ("19 1/2", "6 1/2", False), ("19 1/2", "6 1/2", False)
    ]
    


    converted = [
        (parse_inches(w), parse_inches(h), f"{w} x {h}", is_bracket)
        for w, h, is_bracket in raw_pieces
    ]
    
    # === ⏱️ Start Execution Timer ===
    start_time = time.time()

    # Run placement algorithm
    placements = place_rectangles(SHEET_WIDTH, SHEET_HEIGHT, converted)

    # === ⏱️ End Execution Timer ===
    end_time = time.time()

    print(f"\n✅ Layout complete: {len(placements)} pieces placed")
    print(f"🕒 Execution Time: {end_time - start_time:.4f} seconds")

    visualize(SHEET_WIDTH, SHEET_HEIGHT, placements)