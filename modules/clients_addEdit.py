# modules/clients_addEdit.py
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QComboBox, QMessageBox,
    QFrame, QScrollArea
)
from PyQt5.QtCore import Qt
from firebase.config import db
from firebase_admin import firestore
import random

class ClientsPage(QMainWindow):
    def __init__(self, user_data):
        super().__init__()
        self.setWindowTitle("Clients - Add / Edit")
        self.setMinimumSize(1000, 600)

        self.user_data = user_data
        self.selected_branch = None
        self.selected_category_id = None
        self.selected_customer_id = None

        self.branches = user_data.get("branch", [])
        if isinstance(self.branches, str):
            self.branches = [self.branches]
        self.selected_branch = self.branches[0]

        self.categories = []
        self.customers = []

        self.build_ui()
        self.refresh_categories()

    def build_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        title = QLabel("🧾 Client Management Panel")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        main_layout.addWidget(title)

        # Branch dropdown
        branch_row = QHBoxLayout()
        branch_label = QLabel("Branch:")
        self.branch_combo = QComboBox()
        self.branch_combo.addItems(self.branches)
        self.branch_combo.currentTextChanged.connect(self.on_branch_change)
        branch_row.addWidget(branch_label)
        branch_row.addWidget(self.branch_combo)
        branch_row.addStretch()
        main_layout.addLayout(branch_row)

        # Panels
        panels = QHBoxLayout()
        main_layout.addLayout(panels, stretch=1)

        # --- Left Panel: Category List ---
        self.category_list = QListWidget()
        self.category_list.itemSelectionChanged.connect(self.load_customers_for_category)
        cat_section = QVBoxLayout()
        cat_section.addWidget(QLabel("Main Customer Categories"))
        cat_section.addWidget(self.category_list)

        self.cat_input = QLineEdit()
        self.cat_input.setPlaceholderText("Category Name")
        cat_section.addWidget(self.cat_input)

        cat_buttons = QHBoxLayout()
        cat_buttons.addWidget(QPushButton("Add", clicked=self.add_category))
        cat_buttons.addWidget(QPushButton("Edit", clicked=self.edit_category))
        cat_buttons.addWidget(QPushButton("Delete", clicked=self.delete_category))
        cat_section.addLayout(cat_buttons)

        cat_frame = QFrame()
        cat_frame.setLayout(cat_section)
        cat_frame.setMinimumWidth(300)
        panels.addWidget(cat_frame)

        # --- Right Panel: Customers ---
        right_layout = QVBoxLayout()

        self.customer_list = QListWidget()
        self.customer_list.itemSelectionChanged.connect(self.fill_customer_form)
        right_layout.addWidget(QLabel("Customers"))
        right_layout.addWidget(self.customer_list)

        self.entry_id = QLineEdit()
        self.entry_id.setPlaceholderText("Customer ID")
        self.entry_id.setDisabled(True)

        self.entry_name = QLineEdit()
        self.entry_name.setPlaceholderText("Customer Name")

        phone_row = QHBoxLayout()
        self.entry_phone = QLineEdit()
        self.entry_phone.setPlaceholderText("Phone Number")
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self.search_by_phone)
        phone_row.addWidget(self.entry_phone)
        phone_row.addWidget(search_btn)

        self.entry_address = QLineEdit()
        self.entry_address.setPlaceholderText("Address")

        right_layout.addWidget(self.entry_id)
        right_layout.addWidget(self.entry_name)
        right_layout.addLayout(phone_row)
        right_layout.addWidget(self.entry_address)

        cust_buttons = QHBoxLayout()
        cust_buttons.addWidget(QPushButton("Add", clicked=self.add_customer))
        cust_buttons.addWidget(QPushButton("Edit", clicked=self.edit_customer))
        cust_buttons.addWidget(QPushButton("Delete", clicked=self.delete_customer))
        cust_buttons.addWidget(QPushButton("Clear", clicked=self.clear_form))
        right_layout.addLayout(cust_buttons)

        right_frame = QFrame()
        right_frame.setLayout(right_layout)
        panels.addWidget(right_frame, stretch=2)

    def on_branch_change(self, branch):
        self.selected_branch = branch
        self.refresh_customers()

    def refresh_categories(self):
        self.category_list.clear()
        self.categories = []
        docs = db.collection("client_categories").stream()
        for doc in docs:
            data = doc.to_dict()
            self.categories.append((doc.id, data["name"]))
            self.category_list.addItem(data["name"])

    def load_customers_for_category(self):
        selected_items = self.category_list.selectedItems()
        if not selected_items:
            return
        index = self.category_list.currentRow()
        self.selected_category_id = self.categories[index][0]
        self.refresh_customers()

    def refresh_customers(self):
        self.customer_list.clear()
        self.customers = []
        if not self.selected_category_id or not self.selected_branch:
            return

        docs = db.collection("clients") \
            .where("category_id", "==", self.selected_category_id) \
            .where("branch", "==", self.selected_branch).stream()

        for doc in docs:
            data = doc.to_dict()
            self.customers.append((doc.id, data.get("name", ""), data.get("customer_id", "")))
            self.customer_list.addItem(f"{data.get('customer_id', '')} - {data.get('name', '')}")

    def search_by_phone(self):
        phone = self.entry_phone.text().strip()
        if not phone:
            QMessageBox.warning(self, "Error", "Enter phone number to search.")
            return

        for i, (doc_id, name, customer_id) in enumerate(self.customers):
            doc = db.collection("clients").document(doc_id).get()
            if doc.exists:
                data = doc.to_dict()
                if data.get("phone") == phone:
                    self.entry_id.setText(data.get("customer_id", ""))
                    self.entry_name.setText(data.get("name", ""))
                    self.entry_address.setText(data.get("address", ""))
                    self.customer_list.setCurrentRow(i)
                    return

        QMessageBox.information(self, "Not Found", "No customer found with that phone number.")

    def add_category(self):
        name = self.cat_input.text().strip()
        if name:
            db.collection("client_categories").add({"name": name})
            self.cat_input.clear()
            self.refresh_categories()

    def edit_category(self):
        index = self.category_list.currentRow()
        if index >= 0:
            name = self.cat_input.text().strip()
            if name:
                cat_id = self.categories[index][0]
                db.collection("client_categories").document(cat_id).update({"name": name})
                self.refresh_categories()

    def delete_category(self):
        index = self.category_list.currentRow()
        if index >= 0:
            cat_id = self.categories[index][0]
            db.collection("client_categories").document(cat_id).delete()
            self.refresh_categories()
            self.customer_list.clear()

    def fill_customer_form(self):
        index = self.customer_list.currentRow()
        if index >= 0:
            cust_id = self.customers[index][0]
            doc = db.collection("clients").document(cust_id).get()
            if doc.exists:
                data = doc.to_dict()
                self.entry_id.setText(data.get("customer_id", ""))
                self.entry_name.setText(data.get("name", ""))
                self.entry_phone.setText(data.get("phone", ""))
                self.entry_address.setText(data.get("address", ""))
                self.selected_customer_id = cust_id

    def add_customer(self):
        if not self.selected_category_id or not self.selected_branch:
            QMessageBox.warning(self, "Error", "Select category and branch first.")
            return

        name = self.entry_name.text().strip()
        phone = self.entry_phone.text().strip()
        address = self.entry_address.text().strip()
        if name:
            customer_id = str(random.randint(10000, 99999))
            db.collection("clients").add({
                "name": name,
                "phone": phone,
                "address": address,
                "category_id": self.selected_category_id,
                "customer_id": customer_id,
                "branch": self.selected_branch,
                "created_at": firestore.SERVER_TIMESTAMP,
                "order_ids": []
            })
            self.clear_form()
            self.refresh_customers()

    def edit_customer(self):
        index = self.customer_list.currentRow()
        if index >= 0:
            name = self.entry_name.text().strip()
            phone = self.entry_phone.text().strip()
            address = self.entry_address.text().strip()
            if name:
                cust_id = self.customers[index][0]
                db.collection("clients").document(cust_id).update({
                    "name": name,
                    "phone": phone,
                    "address": address
                })
                self.clear_form()
                self.refresh_customers()

    def delete_customer(self):
        index = self.customer_list.currentRow()
        if index >= 0:
            cust_id = self.customers[index][0]
            db.collection("clients").document(cust_id).delete()
            self.clear_form()
            self.refresh_customers()

    def clear_form(self):
        self.entry_id.clear()
        self.entry_name.clear()
        self.entry_phone.clear()
        self.entry_address.clear()
