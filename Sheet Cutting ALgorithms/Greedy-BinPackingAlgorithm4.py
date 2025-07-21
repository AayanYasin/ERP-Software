import matplotlib.pyplot as plt
from fractions import Fraction
from math import ceil
import time
from collections import defaultdict

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
                px = int(round((x + dx / resolution) * resolution))
                py = int(round((y + dy / resolution) * resolution))
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

# ========== FASTER FALLBACK OPTIMIZER ==========

def optimize_layout(sheet_w, sheet_h, cuts):
    from copy import deepcopy
    print("[TEST] Running fallback optimizer unit test")

    try:
        print("[PERF] Starting optimizer profiling...")
        start_time = time.time()
        def dp_find_best_row(pieces, max_width):
            n = len(pieces)
            dp = [{} for _ in range(n + 1)]  # dp[i][w] = (total, items)

            dp[0][0] = (0, [])

            for i in range(1, n + 1):
                w0, h0, label, is_bracket = pieces[i - 1]
                orientations = [(w0, h0), (h0, w0)]
                for prev_w, (total, items) in dp[i - 1].items():
                    for w, h in orientations:
                        new_w = prev_w + w
                        if new_w <= max_width:
                            new_total = total + w
                            new_items = items + [(w, h, label, is_bracket, i - 1)]
                            if new_w not in dp[i] or dp[i][new_w][0] < new_total:
                                dp[i][new_w] = (new_total, new_items)

                    if prev_w not in dp[i] or dp[i][prev_w][0] < total:
                        dp[i][prev_w] = (total, items)

            best_total = 0
            best_items = []
            for total, items in dp[n].values():
                if total > best_total:
                    best_total = total
                    best_items = items

            if not best_items:
                return None

            used_indexes = [idx for *_, idx in best_items]
            used_items = [pieces[i] for i in used_indexes]
            row = [item[:4] for item in best_items]
            return used_items, row

        parsed = [tuple(cut) for cut in cuts]
        y_cursor = 0
        layout = []

        while parsed:
            result = dp_find_best_row(parsed, sheet_w)
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
    
    except Exception as e:
        print(f"[ERROR] Optimizer failed: {e}")
        return []

# ========== RECTANGLE PLACEMENT ==========

def place_rectangles(sheet_w, sheet_h, rectangles, fallback_allowed=True):
    print("[TEST] Starting rectangle placement test")
    try:
        used = []
        current_y = 0
        row_height = 0
        current_x = 0
        scan_resolution = 8

        unplaced = []

        for rect in rectangles:
            w, h, label, is_bracket = rect
            placed = False

            if current_x + w <= sheet_w and current_y + h <= sheet_h:
                overlaps = any(
                    not (current_x + w <= ux or ux + uw <= current_x or
                        current_y + h <= uy or uy + uh <= current_y)
                    for ux, uy, uw, uh, *_ in used
                )
                if not overlaps:
                    used.append((current_x, current_y, w, h, label, is_bracket))
                    current_x += w
                    row_height = max(row_height, h)
                    placed = True

            if not placed:
                new_y = current_y + row_height
                if new_y + h <= sheet_h:
                    overlaps = any(
                        not (0 + w <= ux or ux + uw <= 0 or
                            new_y + h <= uy or uy + uh <= new_y)
                        for ux, uy, uw, uh, *_ in used
                    )
                    if not overlaps:
                        current_y = new_y
                        current_x = 0
                        row_height = h
                        used.append((current_x, current_y, w, h, label, is_bracket))
                        current_x += w
                        placed = True

            if not placed:
                waste_blocks = scan_waste_blocks(sheet_w, sheet_h, used)
                for wx, wy, ww, wh in waste_blocks:
                    candidate_positions = [(wx, wy, w, h), (wx, wy, h, w)] if w != h else [(wx, wy, w, h)]

                    for px, py, pw, ph in candidate_positions:
                        if pw > ww or ph > wh:
                            continue

                        # Check for overlap with already placed rectangles
                        overlaps = any(
                            not (px + pw <= ux or ux + uw <= px or py + ph <= uy or uy + uh <= py)
                            for ux, uy, uw, uh, *_ in used
                        )

                        if not overlaps:
                            used.append((px, py, pw, ph, label, is_bracket))
                            placed = True
                            break

                    if placed:
                        break

            if not placed:
                grid_w = int(sheet_w * scan_resolution)
                grid_h = int(sheet_h * scan_resolution)
                grid = [[False for _ in range(grid_w)] for _ in range(grid_h)]

                for ux, uy, uw, uh, *_ in used:
                    for dx in range(int(uw * scan_resolution)):
                        for dy in range(int(uh * scan_resolution)):
                            gx = int(round((ux + dx / scan_resolution) * scan_resolution))
                            gy = int(round((uy + dy / scan_resolution) * scan_resolution))
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

            if not placed and fallback_allowed:
                optimized = optimize_layout(sheet_w, sheet_h, rectangles)
                return place_rectangles(sheet_w, sheet_h, optimized, fallback_allowed=False)

            if not placed:
                unplaced.append(label)

        return used, unplaced
    
    except Exception as e:
        print(f"[ERROR] Rectangle placement failed: {e}")
        return [], [label for _, _, label, _ in rectangles]

# ========== VISUALIZATION ==========

def visualize(sheet_w, sheet_h, placed_rects):
    print("[TEST] Visualizing layout (unit test for display)")
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

# ========== MAIN WORKFLOW ==========

def smart_group_sort(raw_pieces):
    grouped = defaultdict(list)
    for piece in raw_pieces:
        grouped[(piece[0], piece[1])].append(piece)

    def smart_sort_key(k):
        w = parse_inches(k[0])
        h = parse_inches(k[1])
        count = len(grouped[k])
        if w == 0:
            return (0, 0, 0)
        ratio = h / w
        return (-ratio * count, -count, -h)

    sorted_keys = sorted(grouped.keys(), key=smart_sort_key)
    return [p for key in sorted_keys for p in grouped[key]]

def run_layout(raw_pieces):
    print("[TEST] Running layout unit test case")
    try:
        # sorted_pieces = smart_group_sort(raw_pieces)

        # --- Convert to float + labels
        converted = [
            (parse_inches(w), parse_inches(h), f"{w} x {h}", is_bracket)
            for w, h, is_bracket in raw_pieces
        ]
        print("[PERF] Starting layout placement profiling...")
        start_time = time.time()

        placements, unplaced = place_rectangles(SHEET_WIDTH, SHEET_HEIGHT, converted)

        end_time = time.time()
        print(f"[PERF] Layout Complete: {len(placements)} pieces placed")
        print(f"[PERF] Layout placement time: {end_time - start_time:.4f} seconds")

        if unplaced:
            print(f"\n⚠️ Unplaced pieces ({len(unplaced)}):")
            for label in unplaced:
                print(f"  • {label}")

        return placements

    except Exception as e:
        print(f"[ERROR] Layout generation failed: {e}")
        return []

# ========== MAIN ==========

if __name__ == "__main__":
    SHEET_WIDTH = 48.0
    SHEET_HEIGHT = 96.0

    raw_pieces = [
        *[("6 1/2", "16 1/2", False)]*35,
        *[("19 1/2", "6 1/2", False)]*4,
        *[("4 1/2", "13 1/2", False)]*2,
    ]

    sorted_pieces = smart_group_sort(raw_pieces)

    rectangles = [(parse_inches(w), parse_inches(h), rot) for w, h, rot in sorted_pieces]
    total_cut_area = sum(w * h for w, h, *_ in rectangles)
    sheet_area = SHEET_WIDTH * SHEET_HEIGHT

    if sheet_area >= total_cut_area:
        placements = run_layout(sorted_pieces)
        visualize(SHEET_WIDTH, SHEET_HEIGHT, placements)
    else:
        print(f"SKIPPED: Total cut area: {total_cut_area:.2f} in² > Sheet area: {sheet_area:.2f} in²")
        