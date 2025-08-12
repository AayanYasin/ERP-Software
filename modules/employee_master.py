from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QFormLayout, QLineEdit, QComboBox,
    QMessageBox, QHBoxLayout, QDateEdit, QLabel
)
from PyQt5.QtCore import Qt, QDate
from firebase.config import db
from datetime import datetime
import uuid


class EmployeeMaster(QWidget):
    def __init__(self, user_data):
        super().__init__()
        self.setWindowTitle("Employee Master")
        self.layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.code_edit = QLineEdit()
        self.code_edit.setReadOnly(True)
        self.cnic_edit = QLineEdit()
        self.designation_edit = QLineEdit()
        self.department_edit = QLineEdit()
        self.contact_edit = QLineEdit()
        self.email_edit = QLineEdit()
        self.branch_edit = QLineEdit()
        self.user_data = user_data

        self.salary_type_combo = QComboBox()
        self.salary_type_combo.addItems(["Monthly", "Weekly"])

        self.salary_edit = QLineEdit()
        self.advance_edit = QLineEdit()
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Active", "Inactive", "Terminated"])

        self.date_joined = QDateEdit()
        self.date_joined.setDate(QDate.currentDate())
        self.date_joined.setCalendarPopup(True)

        self.save_button = QPushButton("Save Employee")
        self.save_button.clicked.connect(self.save_employee)

        self.form_layout.addRow("Name", self.name_edit)
        self.form_layout.addRow("Employee Code", self.code_edit)
        self.form_layout.addRow("CNIC", self.cnic_edit)
        self.form_layout.addRow("Designation", self.designation_edit)
        self.form_layout.addRow("Department", self.department_edit)
        self.form_layout.addRow("Branch", self.branch_edit)
        self.form_layout.addRow("Contact", self.contact_edit)
        self.form_layout.addRow("Email", self.email_edit)
        self.form_layout.addRow("Date Joined", self.date_joined)
        self.form_layout.addRow("Salary Type", self.salary_type_combo)
        self.form_layout.addRow("Salary", self.salary_edit)
        self.form_layout.addRow("Advance", self.advance_edit)
        self.form_layout.addRow("Status", self.status_combo)

        self.layout.addLayout(self.form_layout)
        self.layout.addWidget(self.save_button)

        self.generate_employee_code()

    def generate_employee_code(self):
        employees_ref = db.collection("employees")
        count = len(employees_ref.get())
        code = f"EMP-{str(count + 1).zfill(3)}"
        self.code_edit.setText(code)

    def save_employee(self):
        name = self.name_edit.text().strip()
        code = self.code_edit.text().strip()
        cnic = self.cnic_edit.text().strip()
        designation = self.designation_edit.text().strip()
        department = self.department_edit.text().strip()
        branch = self.branch_edit.text().strip()
        contact = self.contact_edit.text().strip()
        email = self.email_edit.text().strip()
        date_joined = self.date_joined.date().toString("yyyy-MM-dd")
        salary_type = self.salary_type_combo.currentText()
        salary = float(self.salary_edit.text().strip() or 0)
        advance = float(self.advance_edit.text().strip() or 0)
        status = self.status_combo.currentText()
        account_code = f"3010-{name.upper()}"

        if not name or not branch:
            QMessageBox.warning(self, "Validation Error", "Name and Branch are required.")
            return

        employee_data = {
            "name": name,
            "employee_code": code,
            "cnic": cnic,
            "designation": designation,
            "department": department,
            "contact": contact,
            "email": email,
            "branch": branch,
            "date_joined": date_joined,
            "status": status,
            "salary_type": salary_type,
            "salary": salary,
            "advance": advance,
            "account_code": account_code
        }

        try:
            db.collection("employees").add(employee_data)
            self.create_employee_account_in_coa(name, account_code, branch)
            if advance > 0:
                self.create_advance_journal_entry(account_code, advance, branch)

            QMessageBox.information(self, "Success", f"Employee '{name}' added successfully!")
            self.clear_form()
            self.generate_employee_code()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def create_employee_account_in_coa(self, name, code, branch):
        coa_doc = {
            "code": code,
            "name": name,
            "type": "Liability",
            "parent": "3010",  # Assuming Employee Payables
            "branches": [branch],
            "active": True,
            "description": f"Employee Account for {name}"
        }
        db.collection("chart_of_accounts").document(code).set(coa_doc)

    def create_advance_journal_entry(self, employee_account, amount, branch):
        entry_id = str(uuid.uuid4())
        date = datetime.now().strftime("%Y-%m-%d")
        journal_entry = {
            "id": entry_id,
            "date": date,
            "description": f"Advance paid to employee {employee_account}",
            "branch": branch,
            "status": "Posted",
            "lines": [
                {"account": "1000-CASH", "debit": amount, "credit": 0},  # You can make cash/bank dynamic later
                {"account": employee_account, "debit": 0, "credit": amount}
            ]
        }
        db.collection("journal_entries").document(entry_id).set(journal_entry)

    def clear_form(self):
        for widget in [self.name_edit, self.cnic_edit, self.designation_edit, self.department_edit,
                       self.branch_edit, self.contact_edit, self.email_edit,
                       self.salary_edit, self.advance_edit]:
            widget.clear()
        self.status_combo.setCurrentIndex(0)
        self.salary_type_combo.setCurrentIndex(0)
        self.date_joined.setDate(QDate.currentDate())
