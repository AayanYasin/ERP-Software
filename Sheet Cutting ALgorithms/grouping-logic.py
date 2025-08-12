from collections import defaultdict
from fractions import Fraction

# --- Parse inch-based dimensions like "6 1/2"
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

# --- Your raw cut list
# SHEET_WIDTH = 48.0
# SHEET_HEIGHT = 96.0

# raw_pieces = [
#   ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False),
#   ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False),
#   ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False),
#   ("12", "31 3/8", False), ("12", "31 3/8", False), ("12", "31 3/8", False)
# ]

# SHEET_WIDTH = 48.0
# SHEET_HEIGHT = 96.0

# raw_pieces = [
#     ("9", "40 3/8", False), ("9", "40 3/8", False), ("9", "40 3/8", False), ("9", "40 3/8", False),
#     ("9", "40 3/8", False), ("9", "40 3/8", False), ("9", "40 3/8", False), ("9", "40 3/8", False),
#     ("12", "40 3/8", False), ("12", "40 3/8", False), ("46 3/8", "12", False)
# ]

# SHEET_WIDTH = 48.0
# SHEET_HEIGHT = 96.0

# raw_pieces = [
#     ("9", "37 3/8", False), ("9", "37 3/8", False), ("9", "37 3/8", False), ("9", "37 3/8", False),
#     ("9", "37 3/8", False), ("9", "37 3/8", False), ("9", "37 3/8", False), ("9", "37 3/8", False),
#     ("12", "37 3/8", False), ("12", "37 3/8", False), ("46 3/8", "12", False), ("46 3/8", "9", False)
# ]

# SHEET_WIDTH = 48.0
# SHEET_HEIGHT = 96.0

# raw_pieces = [
#     ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False),
#     ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False),
#     ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False), ("9", "31 3/8", False),
#     ("12", "31 3/8", False), ("12", "31 3/8", False), ("12", "31 3/8", False)
# ]

# SHEET_WIDTH = 48.0
# SHEET_HEIGHT = 77.0

# raw_pieces = [
#     ("9", "25 3/8", False), ("9", "25 3/8", False), ("9", "25 3/8", False), ("9", "25 3/8", False),
#     ("9", "25 3/8", False), ("9", "25 3/8", False), ("9", "25 3/8", False), ("9", "25 3/8", False),
#     ("9", "25 3/8", False), ("9", "25 3/8", False), ("9", "25 3/8", False), ("9", "25 3/8", False),
#     ("12", "25 3/8", False), ("12", "25 3/8", False), ("12", "25 3/8", False)
# ]

# SHEET_WIDTH = 48.0
# SHEET_HEIGHT = 96.0

# raw_pieces = [
# *[("6 1/2", "16 1/2", False)]*35,
# *[("4 1/2", "13 1/2", False)]*2,
# *[("19 1/2", "6 1/2", False)]*4,
# ]

# SHEET_WIDTH = 49.0
# SHEET_HEIGHT = 106.0

# raw_pieces = [
#     *[("21", "53", False)]*4,
#     *[("3 1/2", "53", False)]*4
# ]

# SHEET_WIDTH = 48.0
# SHEET_HEIGHT = 78.0

raw_pieces = [
        *[("11", "78", False)]*1,
        *[("27", "39", False)]*2,
        *[("5", "39", False)]*4,
    ]

# --- Group identical parts by (width, height)
grouped = defaultdict(list)
for piece in raw_pieces:
    grouped[(piece[0], piece[1])].append(piece)

# --- Improved sort key: prioritize height, then narrower widths, then higher counts
def nesting_sort_key(k):
    w = parse_inches(k[0])
    h = parse_inches(k[1])
    count = len(grouped[k])
    return (-h, -w, -count)

# --- Sort group keys
sorted_group_keys = sorted(grouped.keys(), key=nesting_sort_key)

# --- Flatten final cut list based on sorted groups
final_sorted_list = [piece for key in sorted_group_keys for piece in grouped[key]]

# --- Output result
print("📦 Final Grouped & Sorted Cut Order:\n")
for i, p in enumerate(final_sorted_list, 1):
    print(f"{i:02d}. {p}")
