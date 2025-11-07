from firebase.config import db
import random
import string

user_branches = ["Gulshan", "Orangi Town"]

def generate_item_code():
    return ''.join(random.choices(string.digits, k=7))

sheet_sub_id = "hjz5VgjdMMr3O7nZ7EIg"
pipe_sub_id = "YJf8BGcjahI2YdnrC9Kk"

raw_material_sheets = [
    {"name": "Steel Sheet", "length": 96, "width": 48, "height": 0, "length_unit": "inch", "width_unit": "inch", "height_unit": "inch", "weight": 12.5, "weight_unit": "kg", "gauge": 18, "color": "Silver", "condition": "New", "selling_price": 3000, "reorder_qty": 5, "metal_type": "Sheet"},
    {"name": "Aluminum Sheet", "length": 72, "width": 36, "height": 0.2, "length_unit": "inch", "width_unit": "inch", "height_unit": "inch", "weight": 10.0, "weight_unit": "kg", "gauge": 20, "color": "Gray", "condition": "New", "selling_price": 2800, "reorder_qty": 6},
]

raw_material_pipes = [
    {"name": "Steel Pipe", "length": 20, "width": 2, "height": 2, "length_unit": "ft", "width_unit": "inch", "height_unit": "inch", "weight": 6.0, "weight_unit": "kg", "gauge": 16, "color": "Black", "condition": "New", "selling_price": 1500, "reorder_qty": 12, "metal_type": "Pipe"},
    {"name": "PVC Pipe", "length": 10, "width": 1.5, "height": 1.5, "length_unit": "ft", "width_unit": "inch", "height_unit": "inch", "weight": 3.0, "weight_unit": "kg", "gauge": 18, "color": "White", "condition": "New", "selling_price": 800, "reorder_qty": 8},
]

finished_products = [
    {"name": "Bookshelf", "length": 60, "width": 30, "height": 72, "length_unit": "inch", "width_unit": "inch", "height_unit": "inch", "weight": 30.0, "weight_unit": "kg", "gauge": 0, "color": "Brown", "condition": "New", "selling_price": 7000, "reorder_qty": 2},
    {"name": "Shoe Rack", "length": 36, "width": 18, "height": 48, "length_unit": "inch", "width_unit": "inch", "height_unit": "inch", "weight": 18.0, "weight_unit": "kg", "gauge": 0, "color": "White", "condition": "New", "selling_price": 4500, "reorder_qty": 3},
    {"name": "Wall Cabinet", "length": 24, "width": 12, "height": 30, "length_unit": "inch", "width_unit": "inch", "height_unit": "inch", "weight": 10.0, "weight_unit": "kg", "gauge": 0, "color": "Grey", "condition": "New", "selling_price": 3800, "reorder_qty": 4},
]

def add_item(base, sub_id, is_raw):
    item = base.copy()
    item["item_code"] = generate_item_code()
    item["gauge"] += random.choice([-1, 0, 1]) if item.get("gauge") else 0
    item["length"] += round(random.uniform(-1, 1), 1)
    item["width"] += round(random.uniform(-1, 1), 1)
    item["weight"] += round(random.uniform(-0.5, 0.5), 1)
    item["selling_price"] += random.randint(-100, 150)
    item["qty"] = {branch: random.randint(0, 50) for branch in user_branches}
    item["sub_id"] = sub_id
    item["sample_batch"] = True
    item["type"] = item.get("metal_type", "") if is_raw else ""

    # Ensure clean if finished product
    if not is_raw:
        item.pop("metal_type", None)

    db.collection("products").add(item)
    print(f"✅ Added: {item['name']} [{item['item_code']}] {'(Raw)' if is_raw else '(Finished)'}")

def push_all():
    print("🚀 Adding 30 products (10 sheets, 10 pipes, 10 finished)...")

    # 10 Metal Sheets
    for _ in range(10):
        base = random.choice(raw_material_sheets)
        add_item(base, sheet_sub_id, is_raw=True)

    # 10 Metal Pipes
    for _ in range(10):
        base = random.choice(raw_material_pipes)
        add_item(base, pipe_sub_id, is_raw=True)

    # 10 Finished Products
    for _ in range(10):
        base = random.choice(finished_products)
        sub_id = random.choice([sheet_sub_id, pipe_sub_id])  # simulate finished products built from raw
        add_item(base, sub_id, is_raw=False)

    print("🎉 All done.")

def delete_sample_products():
    print("🧹 Deleting all sample products...")
    docs = db.collection("products").where("sample_batch", "==", True).stream()
    count = 0
    for doc in docs:
        db.collection("products").document(doc.id).delete()
        count += 1
    print(f"🗑️ Deleted {count} sample items.")

if __name__ == "__main__":
    choice = input("📦 Choose:\n1. Add Sample Products\n2. Delete Sample Products\n👉 Enter choice (1/2 or add/delete): ").strip().lower()

    if choice in ["1", "add"]:
        push_all()
    elif choice in ["2", "delete"]:
        delete_sample_products()
    else:
        print("❌ Invalid choice. Exiting.")
