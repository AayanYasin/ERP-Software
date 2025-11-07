from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

def create_expandable_sidebar(parent, items, logout_command, font_scale=1.0):
    sidebar_widget = QWidget()
    sidebar_widget.setStyleSheet("background-color: #2d3436;")
    sidebar_layout = QVBoxLayout(sidebar_widget)
    sidebar_layout.setContentsMargins(10, 10, 10, 10)
    sidebar_layout.setSpacing(5)

    font_base = QFont("Segoe UI", int(12 * font_scale))
    font_bold = QFont("Segoe UI", int(12 * font_scale), QFont.Bold)
    sub_font = QFont("Segoe UI", int(11 * font_scale))

    def toggle_submenu(parent_btn, submenu_widgets):
        expanded = parent_btn.property("expanded")
        if expanded:
            for w in submenu_widgets:
                w.hide()
            parent_btn.setText(parent_btn.text().replace("▼", "▶"))
        else:
            for w in submenu_widgets:
                w.show()
            parent_btn.setText(parent_btn.text().replace("▶", "▼"))
        parent_btn.setProperty("expanded", not expanded)

    for item in items:
        if isinstance(item, tuple) and isinstance(item[1], list):
            parent_text = item[0]
            sub_items = item[1]

            parent_btn = QPushButton(f"▶ {parent_text}")
            parent_btn.setFont(font_bold)
            parent_btn.setStyleSheet("""
                QPushButton {
                    text-align: left; padding: 8px;
                    background-color: #2d3436;
                    color: white; border: none;
                }
                QPushButton:hover {
                    background-color: #636e72;
                }
            """)
            parent_btn.setProperty("expanded", False)
            sidebar_layout.addWidget(parent_btn)

            submenu_widgets = []
            for sub_text, sub_command in sub_items:
                sub_btn = QPushButton(f"    - {sub_text}")
                sub_btn.setFont(sub_font)
                sub_btn.setStyleSheet("""
                    QPushButton {
                        text-align: left; padding: 6px;
                        background-color: #2d3436;
                        color: white; border: none;
                    }
                    QPushButton:hover {
                        background-color: #636e72;
                    }
                """)
                sub_btn.clicked.connect(sub_command)
                sub_btn.hide()
                sidebar_layout.addWidget(sub_btn)
                submenu_widgets.append(sub_btn)

            parent_btn.clicked.connect(lambda _, b=parent_btn, w=submenu_widgets: toggle_submenu(b, w))

        else:
            text, command = item
            btn = QPushButton(text)
            btn.setFont(font_base)
            btn.setStyleSheet("""
                QPushButton {
                    text-align: left; padding: 8px;
                    background-color: #2d3436;
                    color: white; border: none;
                }
                QPushButton:hover {
                    background-color: #636e72;
                }
            """)
            btn.clicked.connect(command)
            sidebar_layout.addWidget(btn)

    # Logout button at bottom
    sidebar_layout.addStretch()
    logout_btn = QPushButton("Logout")
    logout_btn.setFont(font_bold)
    logout_btn.setStyleSheet("""
        QPushButton {
            text-align: left; padding: 10px;
            background-color: #d63031;
            color: white; border: none;
        }
        QPushButton:hover {
            background-color: #c0392b;
        }
    """)
    logout_btn.clicked.connect(logout_command)
    sidebar_layout.addWidget(logout_btn)

    # Let sidebar size to content naturally
    sidebar_widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding)
    sidebar_widget.adjustSize()

    return sidebar_widget
