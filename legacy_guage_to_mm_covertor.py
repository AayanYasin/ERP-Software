#!/usr/bin/env python3
"""
Convert legacy gauge numbers to mm for products in a given item_code range.

- Prompts for start and end item_code (inclusive).
- Reads products whose item_code is between those values.
- If 'gauge' looks like a legacy gauge number (e.g., 22), converts it to mm (e.g., 0.8).
- If 'gauge' already looks like mm (<= 5.0 and > 0), leaves it alone.
- Keeps the Firestore field name 'gauge'; only the value changes to float mm.

Requires: from firebase.config import db
"""

from firebase.config import db  # your existing Firestore db instance
from typing import Tuple

# Legacy gauge-number → mm mapping (as used in your app)
GAUGE_TO_MM = {
    11: 3.0, 12: 2.5, 13: 2.5, 14: 2.0, 16: 1.5, 18: 1.2,
    20: 1.0, 22: 0.8, 23: 0.7, 24: 0.6, 26: 0.55, 28: 0.5
}


def read_range() -> Tuple[str, str]:
    """Prompt user for start/end item_code (kept as strings for Firestore range query)."""
    start_code = input("Start item_code (inclusive): ").strip()
    end_code = input("End item_code (inclusive): ").strip()
    if not start_code or not end_code:
        raise SystemExit("Both start and end item_code are required.")
    return start_code, end_code


def is_already_mm(value) -> bool:
    """
    Heuristic: if numeric and 0 < value <= 5.0, treat as mm already.
    (Your mm values like 0.8, 1.2, 2.0, 3.0, etc., are all <= 5.)
    """
    try:
        v = float(str(value).strip())
        return 0 < v <= 5.0
    except Exception:
        return False


def coerce_to_number(value):
    """Try to coerce Firestore value to numeric (int if integer-looking else float)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    s = str(value).strip()
    if not s:
        return None
    # Prefer int if it looks like an integer
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        try:
            return int(s)
        except Exception:
            pass
    try:
        return float(s)
    except Exception:
        return None


def convert_range(start_code: str, end_code: str):
    print(f"\nAbout to convert 'gauge' → mm for item_code in [{start_code} .. {end_code}]")
    ans = input("Proceed? (y/N): ").strip().lower()
    if ans not in ("y", "yes"):
        print("Aborted.")
        return

    updated = 0
    skipped_mm = 0
    skipped_no_mapping = 0
    total = 0
    touched_ids = []

    # Range query on the same field is allowed; item_code is stored as a string.
    # Your generator uses increasing numeric strings ("1001", "1002", ...) so lex range works fine.
    query = (
        db.collection("products")
        .where("item_code", ">=", start_code)
        .where("item_code", "<=", end_code)
    )

    print("Querying Firestore...")
    docs = list(query.stream())
    print(f"Found {len(docs)} matching documents.\n")

    for snap in docs:
        total += 1
        data = snap.to_dict() or {}
        item_code = data.get("item_code", "")
        g_raw = data.get("gauge", None)

        # Skip if no gauge at all
        if g_raw is None:
            skipped_no_mapping += 1
            print(f"- {item_code}: no 'gauge' field → skipped")
            continue

        # Already mm?
        if is_already_mm(g_raw):
            skipped_mm += 1
            print(f"- {item_code}: already mm ({g_raw}) → skipped")
            continue

        # Try to treat as gauge number and map
        g_num = coerce_to_number(g_raw)
        if g_num is None:
            skipped_no_mapping += 1
            print(f"- {item_code}: non-numeric gauge '{g_raw}' → skipped")
            continue

        g_int = int(round(g_num))
        mm = GAUGE_TO_MM.get(g_int)
        if mm is None:
            skipped_no_mapping += 1
            print(f"- {item_code}: gauge {g_int} not in mapping → skipped")
            continue

        # Update to mm (float), keep field name 'gauge'
        db.collection("products").document(snap.id).update({"gauge": float(mm)})
        updated += 1
        touched_ids.append(snap.id)
        print(f"+ {item_code}: {g_raw} → {mm} mm (updated)")

    print("\n=== Summary ===")
    print(f"Processed            : {total}")
    print(f"Updated to mm        : {updated}")
    print(f"Skipped (already mm) : {skipped_mm}")
    print(f"Skipped (no map/invalid): {skipped_no_mapping}")
    if updated:
        print(f"\nUpdated document IDs (count={updated}):")
        for did in touched_ids:
            print(" -", did)


if __name__ == "__main__":
    s, e = read_range()
    convert_range(s, e)
