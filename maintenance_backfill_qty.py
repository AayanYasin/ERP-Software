# maintenance_backfill_qty_admin.py
# Run with your Firebase Admin SDK env (same as firebase.config)

from firebase.config import db

def fetch_admin_branches():
    """
    Collect a unique set of branches from all admin users.
    Adjust collection/field names if your schema differs.
    """
    branches_set = set()

    # 🔧 If your users live in a different collection or field names differ, edit here
    admin_docs = db.collection("users").where("role", "==", "admin").get()

    for d in admin_docs:
        u = d.to_dict() or {}
        b = u.get("branch", [])
        if isinstance(b, str):
            b = [b]
        for br in b:
            if br:
                branches_set.add(br.strip())

    return sorted(branches_set)

def backfill_all_products_qty_using_admin_branches():
    """
    Backfill products.qty for all products using branches collected from admin users.
    Preserves existing values; only fills missing with 0.
    """
    # Colors like your UI does: meta/colors.pc_colors  【colors source in UI】
    colors_doc = db.collection("meta").document("colors").get()
    colors = (colors_doc.to_dict() or {}).get("pc_colors", [])  # :contentReference[oaicite:2]{index=2}

    # Same three conditions your dialog uses
    conditions = ["New", "Used", "Bad"]  # :contentReference[oaicite:3]{index=3}

    if not colors:
        print("No colors found in meta/colors.pc_colors — aborting.")
        return

    branches = fetch_admin_branches()
    if not branches:
        print("No admin branches found — aborting.")
        return

    print(f"Using admin branches: {branches}")

    batch = db.batch()
    ops = 0
    updated_docs = 0

    for doc in db.collection("products").stream():
        data = doc.to_dict() or {}
        qty = data.get("qty", {}) or {}
        changed = False

        for branch in branches:
            branch_map = qty.get(branch, {})
            # Ensure every color exists
            for color in colors:
                color_map = branch_map.get(color, {})
                # Ensure all 3 conditions exist
                for cond in conditions:
                    if cond not in color_map:
                        color_map[cond] = 0
                        changed = True
                branch_map[color] = color_map
            qty[branch] = branch_map

        if changed:
            batch.update(db.collection("products").document(doc.id), {"qty": qty})
            ops += 1
            updated_docs += 1

            # Commit periodically to avoid batch size limits
            if ops >= 400:
                batch.commit()
                batch = db.batch()
                ops = 0

    if ops:
        batch.commit()

    print(f"Backfill complete. Updated {updated_docs} product(s).")

if __name__ == "__main__":
    backfill_all_products_qty_using_admin_branches()
