# ui/dashboard.py
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QTextEdit,
    QDateEdit, QFrame, QGridLayout, QApplication, QScrollArea, QSizePolicy, QSplitter, QMessageBox
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QFont
from ui.sidebar import create_expandable_sidebar

# Personal Modules
from modules.products import ProductsPage
from modules.stock_adjustment import StockAdjustment
from modules.create_new_login import CreateUserModule
from modules.view_inventory import ViewInventory
from modules.manufacturing_cycle import ManufacturingModule
from modules.view_manufacturing_orders import ViewManufacturingWindow
from modules.settings import SettingsWindow
from modules.chart_of_accounts import ChartOfAccounts
from modules.view_journal_entries import JournalEntryViewer
from modules.employee_master import EmployeeMaster
from modules.clients_master import PartyModule
from modules.invoice import InvoiceModule
# from modules.whatsapp_module import WhatsAppIntegrationWidget
from firebase.config import db


class DashboardApp(QMainWindow):
    def __init__(self, username, user_data):
        super().__init__()
        self.username = username
        self.user_data = user_data
        self.setWindowTitle("ERP Dashboard")
        self.showMaximized()

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.open_windows = []

        self.build_ui()

    def build_ui(self):
        main_layout = QHBoxLayout(self.central_widget)

        sidebar_items = [
            ("Dashboard", lambda: print("Dashboard")),

            ("Parties", [
                ("Manage/View", lambda: self.launch_module("party_window", PartyModule, self.user_data)),
            ]),

            ("Emploees", [
                ("Manage/View", lambda: self.launch_module("Emploee_window", EmployeeMaster, self.user_data)),
            ]),

            ("Accounting", [
                ("Chart of Accounts", lambda: self.launch_module("chart_of_accounts", ChartOfAccounts, self.user_data)),
                ("Open Jounal", lambda: self.launch_module("wiew_journal_entry", JournalEntryViewer, self.user_data)),
            ]),

            ("Sales", [
                ("Invoice", lambda: self.launch_module("invoice_window", InvoiceModule, self.user_data)),
            ]),

            ("Purchase", [
                ("Purchase Order", lambda: QMessageBox.about(self, "Dev Log", "Cannot Acces, Under Development!")),
            ]),

            ("Inventory", [
                ("Chart of Inventory", lambda: self.launch_module("products_window", ProductsPage, self.user_data)),
                ("Stock Adjustment", lambda: self.launch_module("inventory_window", StockAdjustment, self.user_data, self)),
                ("View Inventory", lambda: self.launch_module("view_inventory_window", ViewInventory, self.user_data)),
            ]),

            ("Manufacturing", [
                ("Create Order", lambda: self.launch_module("manufacturing_window", ManufacturingModule)),
                ("View Orders", lambda: self.launch_module("view_orders_window", ViewManufacturingWindow, self.user_data, self)),
            ]),

            ("Core Options", [
                ("Settings", lambda: self.launch_module("settings_window", SettingsWindow, self.user_data)),
                ("Create Login (Admin Only)", lambda: setattr(self, "create_user_window", CreateUserModule.show_if_admin(self.user_data))),
                ("Connect Whatsapp", lambda: QMessageBox.about(self, "Dev Log", "Cannot Acces, Under Development!")),
            ]),
        ]  

        sidebar = create_expandable_sidebar(self, sidebar_items, self.logout, font_scale=1.1)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        content_widget = QWidget()
        scroll_area.setWidget(content_widget)

        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(40, 20, 40, 20)
        content_layout.setSpacing(20)

        # Header
        header = QLabel(f"Welcome, {self.username} - {db.collection("meta").document("company_name").get().to_dict()["name"]} ERP Dashboard")
        header.setFont(QFont("Segoe UI", 18, QFont.Bold))
        header.setStyleSheet("""
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                              stop:0 #74b9ff, stop:1 #0984e3);
            color: white; padding: 18px; border-radius: 10px;
        """)
        content_layout.addWidget(header)

        # Message Board
        label_msg = QLabel("🔔 Message Board")
        label_msg.setFont(QFont("Segoe UI", 16, QFont.Bold))
        content_layout.addWidget(label_msg)

        msg_box = QTextEdit()
        msg_box.setFont(QFont("Segoe UI", 12))
        msg_box.setText("• No pending approvals\n• 2 orders awaiting dispatch\n"
                        "• System running smoothly\n• Welcome, Admin.")
        msg_box.setReadOnly(True)
        msg_box.setStyleSheet("background-color: white; border: 2px solid #dfe6e9; border-radius: 8px;")
        content_layout.addWidget(msg_box)

        # Account Summary Title
        label_summary = QLabel("📊 Account Summary")
        label_summary.setFont(QFont("Segoe UI", 16, QFont.Bold))
        content_layout.addWidget(label_summary)

        # Date Picker
        date_row = QHBoxLayout()
        date_label = QLabel("📅 Date Filter:")
        date_label.setFont(QFont("Segoe UI", 12))
        self.date_picker = QDateEdit(calendarPopup=True)
        self.date_picker.setFont(QFont("Segoe UI", 11))
        self.date_picker.setDate(QDate.currentDate())
        self.date_picker.dateChanged.connect(self.on_date_change)
        self.date_picker.setStyleSheet("padding: 5px; background-color: white; border: 1px solid #b2bec3; border-radius: 5px;")
        date_row.addWidget(date_label)
        date_row.addWidget(self.date_picker)
        date_row.addStretch()
        content_layout.addLayout(date_row)

        self.add_data_table(content_layout, "📈 Sales", "Today's Sales: PKR 0")
        self.add_table_section(content_layout, "💵 Cash & Banks")
        self.add_table_section(content_layout, "🧾 Receivables / Customers")
        self.add_table_section(content_layout, "📄 Payables / Vendors")

        # Inventory Alert
        label_alert = QLabel("📦 Inventory Alert")
        label_alert.setFont(QFont("Segoe UI", 16, QFont.Bold))
        content_layout.addWidget(label_alert)

        alert_box = QLabel("⚠ Total Items (Below Re-Order Level Qty): 0 Items")
        alert_box.setFont(QFont("Segoe UI", 12, QFont.Bold))
        alert_box.setStyleSheet("background-color: #ffeaa7; color: #d63031; padding: 15px; border: 2px solid #fab1a0; border-radius: 8px;")
        content_layout.addWidget(alert_box)

        # Use QSplitter for proportional layout
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(scroll_area)
        splitter.setSizes([150, 1250])  # Sidebar = 350px, Main area = 1050px
        main_layout.addWidget(splitter)

    def add_data_table(self, layout, title, value):
        label = QLabel(title)
        label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(label)

        val_label = QLabel(value)
        val_label.setFont(QFont("Segoe UI", 12))
        val_label.setStyleSheet("background-color: white; padding: 12px; border: 1px solid #dfe6e9; border-radius: 6px;")
        layout.addWidget(val_label)

    def add_table_section(self, layout, title):
        label = QLabel(title)
        label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(label)

        table_frame = QFrame()
        table_layout = QGridLayout()
        headers = ["Opening Balance", "Receipts", "Payments", "Current Balance"]
        for i, text in enumerate(headers):
            th = QLabel(text)
            th.setFont(QFont("Segoe UI", 11, QFont.Bold))
            th.setStyleSheet("background-color: #dfe6e9; border: 1px solid #b2bec3; padding: 8px; border-radius: 4px;")
            table_layout.addWidget(th, 0, i)

        for i, text in enumerate(["NIL"] * 4):
            td = QLabel(text)
            td.setFont(QFont("Segoe UI", 11))
            td.setStyleSheet("background-color: white; border: 1px solid #ccc; padding: 8px; border-radius: 4px;")
            table_layout.addWidget(td, 1, i)

        table_frame.setLayout(table_layout)
        layout.addWidget(table_frame)

    def on_date_change(self, date):
        selected_date = date.toString("yyyy-MM-dd")
        self.load_dashboard_data(selected_date)

    def load_dashboard_data(self, selected_date):
        print(f"[DASHBOARD] Load data for date: {selected_date}")
        
    def launch_module(self, attr_name, window_class, *args):
        win = getattr(self, attr_name, None)

        # Check if window is still alive and visible
        if win:
            if win.isVisible():
                win.raise_()
                win.activateWindow()
                return
            else:
                # It was closed, remove the old reference
                setattr(self, attr_name, None)
                if win in self.open_windows:
                    self.open_windows.remove(win)

        # Create a new instance
        win = window_class(*args)
        setattr(self, attr_name, win)
        self.open_windows.append(win)

        def remove_ref(win=win):
            if win in self.open_windows:
                self.open_windows.remove(win)
            if getattr(self, attr_name, None) == win:
                setattr(self, attr_name, None)

        win.destroyed.connect(remove_ref)
        win.show()
        
    def closeEvent(self, event):
        for win in self.open_windows:
            try:
                if win and win.isVisible():
                    win.close()
            except Exception as e:
                print(f"Failed to close window: {e}")
        event.accept()


    def logout(self):
        self.close()
        from ui.login import LoginWindow  # <--- Lazy import here avoids circular issue
        self.login_window = LoginWindow()
        self.user_data = None
        self.login_window.show()
