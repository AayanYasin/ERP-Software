import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from itertools import combinations, product
from typing import List, Dict


def parse_inches(value: str) -> float:
    """Convert strings like '40 3/8' into float inches."""
    if ' ' in value:
        whole, frac = value.split(' ')
        num, denom = frac.split('/')
        return int(whole) + int(num) / int(denom)
    elif '/' in value:
        num, denom = value.split('/')
        return int(num) / int(denom)
    else:
        return float(value)

# Sheet dimensions
# SHEET_WIDTH = 48.0
# SHEET_HEIGHT = 76.0

# # Input cut pieces (length x width)
# raw_pieces = [
#     ("9", "37 3/8"), ("9", "37 3/8"), ("9", "37 3/8"), ("9", "37 3/8"),
#     ("9", "37 3/8"), ("9", "37 3/8"), ("9", "37 3/8"), ("9", "37 3/8"),
#     ("12", "37 3/8"), ("12", "37 3/8")
# ]

# Sheet dimensions
# SHEET_WIDTH = 48.0
# SHEET_HEIGHT = 96.0

# # Input pieces
# raw_pieces = [
#     ("9", "40 3/8"), ("9", "40 3/8"), ("9", "40 3/8"), ("9", "40 3/8"),
#     ("9", "40 3/8"), ("9", "40 3/8"), ("9", "40 3/8"), ("9", "40 3/8"),
#     ("12", "40 3/8"), ("12", "40 3/8"), ("12", "46 3/8")
# ]

# Input pieces
# raw_pieces = [
#     ("9", "37 3/8"), ("9", "37 3/8"),("9", "37 3/8"),("9", "37 3/8"),("9", "37 3/8"),("9", "37 3/8"),("9", "37 3/8"),("9", "37 3/8"),("12", "37 3/8"),("12", "37 3/8"),("12", "46 3/8"),("9", "46 3/8")
# ]

# raw_pieces = [
#     ("9", "31 3/8"), ("9", "31 3/8"), ("9", "31 3/8"), ("9", "31 3/8"), ("9", "31 3/8"), ("9", "31 3/8"), ("9", "31 3/8"), ("9", "31 3/8"), ("9", "31 3/8"), ("9", "31 3/8"), ("9", "31 3/8"), ("9", "31 3/8"), ("12", "31 3/8"),  ("12", "31 3/8"), ("12", "31 3/8")
# ]

# # Sheet dimensions
SHEET_WIDTH = 48.0
SHEET_HEIGHT = 77.0

raw_pieces = [
    ("9", "25 3/8"), ("9", "25 3/8"), ("9", "25 3/8"), ("9", "25 3/8"), ("9", "25 3/8"), ("9", "25 3/8"), ("9", "25 3/8"), ("9", "25 3/8"), ("9", "25 3/8"), ("9", "25 3/8"), ("9", "25 3/8"), ("9", "25 3/8"),  ("12", "25 3/8"), ("12", "25 3/8"), ("12", "25 3/8")
]

# SHEET_WIDTH = 48
# SHEET_HEIGHT = 96

# raw_pieces = [
#     ("9", "25 3/8")
# ]


# Process the pieces
cut_pieces = []
for idx, (l_str, w_str) in enumerate(raw_pieces):
    l = parse_inches(l_str)
    w = parse_inches(w_str)
    cut_pieces.append({
        'id': idx + 1,
        'length': l,
        'width': w,
        'length_str': l_str,
        'width_str': w_str
    })


def find_best_row(pieces: List[Dict], max_width: float):
    best_combo = []
    best_total_width = 0.0

    # Generate all combinations
    for r in range(1, len(pieces) + 1):
        for combo in combinations(pieces, r):
            # Try all orientation combinations for this combo
            orientations = list(product([0, 1], repeat=len(combo)))  # 0: no rotate, 1: rotate
            for orient in orientations:
                oriented_combo = []
                total_width = 0.0
                valid = True
                for i, piece in enumerate(combo):
                    if orient[i] == 0:
                        pw, ph = piece['length'], piece['width']
                        o = "original"
                    else:
                        pw, ph = piece['width'], piece['length']
                        o = "rotated"

                    if total_width + pw > max_width:
                        valid = False
                        break

                    oriented_combo.append((piece, pw, ph, o))
                    total_width += pw

                if valid and total_width > best_total_width:
                    best_total_width = total_width
                    best_combo = oriented_combo

    return best_combo


def pack_smart_rows_with_rotation(sheet_width: float, sheet_height: float, pieces: List[Dict]):
    y_cursor = 0.0
    remaining = pieces.copy()
    layout = []
    row_num = 0

    while remaining:
        best_row = find_best_row(remaining, sheet_width)
        if not best_row:
            break

        row_height = max(item[2] for item in best_row)  # max height in this row
        if y_cursor + row_height > sheet_height:
            print("Not enough vertical space left.")
            break

        x_cursor = 0.0
        row_num += 1
        print(f"\n--- Row {row_num} ---")

        for piece, pw, ph, orientation in best_row:
            layout.append({
                'index': piece['id'],
                'x': x_cursor,
                'y': y_cursor,
                'width': pw,
                'height': ph,
                'length_str': piece['length_str'],
                'width_str': piece['width_str'],
                'orientation': orientation
            })
            print(f"Placed Piece {piece['id']}: {piece['length_str']} x {piece['width_str']} "
                  f"=> {pw:.2f} x {ph:.2f} at (x={x_cursor:.2f}, y={y_cursor:.2f}), orientation: {orientation}")
            x_cursor += pw
            remaining.remove(piece)

        y_cursor += row_height

    return layout


def draw_layout(layout, sheet_width, sheet_height):
    fig, ax = plt.subplots(figsize=(10, 20))
    ax.set_xlim(0, sheet_width)
    ax.set_ylim(0, sheet_height)
    ax.set_aspect('equal')
    ax.set_title("Optimized Cutting Layout (with Rotation)")
    ax.invert_yaxis()

    # Draw the sheet background
    ax.add_patch(Rectangle((0, 0), sheet_width, sheet_height,
                           edgecolor='black', facecolor='lightgrey', lw=2))

    # Draw the pieces
    for item in layout:
        rect = Rectangle((item['x'], item['y']), item['width'], item['height'],
                         edgecolor='blue', facecolor='skyblue', lw=1.5)
        ax.add_patch(rect)
        label = (f"P{item['index']}\n"
                 f"{item['length_str']} x {item['width_str']}\n"
                 f"{item['orientation']}")
        ax.text(item['x'] + item['width'] / 2, item['y'] + item['height'] / 2,
                label, ha='center', va='center', fontsize=7)

    plt.xlabel("Width (inches)")
    plt.ylabel("Height (inches)")
    plt.grid(True)
    plt.tight_layout()
    plt.show()


# Run everything
layout = pack_smart_rows_with_rotation(SHEET_WIDTH, SHEET_HEIGHT, cut_pieces)
draw_layout(layout, SHEET_WIDTH, SHEET_HEIGHT)
