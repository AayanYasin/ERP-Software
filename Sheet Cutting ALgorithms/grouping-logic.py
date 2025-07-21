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
raw_pieces = [
    ("6 1/2", "16 1/2", False), ("19 1/2", "6 1/2", False), ("6 1/2", "16 1/2", False), ("4 1/2", "13 1/2", False),
    ("6 1/2", "16 1/2", False),  ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False), ("4 1/2", "13 1/2", False), ("19 1/2", "6 1/2", False),
    ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False), ("19 1/2", "6 1/2", False), ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False), ("19 1/2", "6 1/2", False), ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False), ("6 1/2", "16 1/2", False),
    ("6 1/2", "16 1/2", False)
]


# --- Group identical parts by (width, height)
grouped = defaultdict(list)
for piece in raw_pieces:
    grouped[(piece[0], piece[1])].append(piece)

# --- Smart sort key: stack-friendly × group quantity
def smart_sort_key(k):
    w = parse_inches(k[0])
    h = parse_inches(k[1])
    count = len(grouped[k])
    if w == 0:
        return (0, 0, 0)
    ratio = h / w
    return (-ratio * count, -count, -h)

# --- Sort group keys
sorted_group_keys = sorted(grouped.keys(), key=smart_sort_key)

# --- Flatten final cut list based on sorted groups
final_sorted_list = [piece for key in sorted_group_keys for piece in grouped[key]]

# --- Output result
print("📦 Final Grouped & Sorted Cut Order:\n")
for i, p in enumerate(final_sorted_list, 1):
    print(f"{i:02d}. {p}")
