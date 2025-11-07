from firebase.config import db

# Reference to a document
# doc_ref = db.collection('manufacturing_orders').document('B69BaArBpBueG6bvUV48')
a = input("Enter Collection: "); b = input('Enter Document: ')
doc_ref = db.collection(a).document(b)
# doc_ref = db.collection('manufacturing_orders').document('cgUejys5SJdiCYWdwd8P')

# Fetch the document
doc = doc_ref.get()

# Convert to dict if it exists
if doc.exists:
    data = doc.to_dict()
    print(data)  # This will be a dictionary
else:
    print("Document not found")