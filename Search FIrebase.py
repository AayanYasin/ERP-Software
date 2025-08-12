from firebase.config import db

# Reference to a document
# doc_ref = db.collection('manufacturing_orders').document('B69BaArBpBueG6bvUV48')
doc_ref = db.collection('products').document('SgjwlthxwdenHKvQC84c')
# doc_ref = db.collection('manufacturing_orders').document('cgUejys5SJdiCYWdwd8P')

# Fetch the document
doc = doc_ref.get()

# Convert to dict if it exists
if doc.exists:
    data = doc.to_dict()
    print(data)  # This will be a dictionary
else:
    print("Document not found")