# -*- coding: utf-8 -*-
# modules/delivery_chalan.py
# Delivery Chalan module with fastness + requested tweaks:
# Tweaks (2025-09-10):
# 1) Default window sizes set to (1100, 650) for module & dialogs.
# 2) DC number is now RESERVED/ASSIGNED **on Save** (not on dialog open).
# 3) Inventory flattening is robust across branch → color → condition.
# 4) Added detailed filters in the selector: length / width / height / gauge / color / condition.
# 5) Prefill previously selected quantities when reopening the selector.
# 6) Save `mode` and `transfer_to_branch` so the detail dialog shows them.

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QDialog, QFormLayout, QComboBox, QTextEdit, QDialogButtonBox,
    QMessageBox, QHeaderView, QAbstractItemView, QLineEdit, QDateEdit, QToolBar, QAction,
    QGroupBox, QProgressDialog, QStyle, QGridLayout, QSizePolicy, QFileDialog, QPushButton, QMessageBox
)
from PyQt5.QtCore import Qt, QDate, QThread, pyqtSignal, QTimer
import datetime, os, json

# === Use the user's Firestore setup ===
from firebase.config import db
from firebase_admin import firestore

# === PDF generator modules ===
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    _HAS_REPORTLAB = True
except Exception:
    _HAS_REPORTLAB = False

APP_STYLE = """
/* Global */
QWidget { font-size: 14px; }

/* Buttons */
QPushButton { background: #2d6cdf; color: white; border: none; padding: 6px 12px; border-radius: 8px; }
QPushButton:hover { background: #2458b2; }
QPushButton:disabled { background: #a9b7d1; }

/* Group box */
QGroupBox { border: 1px solid #e3e7ef; border-radius: 10px; margin-top: 16px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #4a5568; }

/* Inputs */
QLineEdit, QComboBox, QTextEdit, QDateEdit {
    border: 1px solid #d5dbe7; border-radius: 8px; padding: 6px 8px;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QDateEdit:focus { border-color: #2d6cdf; }

/* Table */
QTableWidget { gridline-color: #e6e9f2; }
QHeaderView::section { background: #f7f9fc; padding: 6px; border: none; border-bottom: 1px solid #e6e9f2; }
"""

def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).strip() or 0)
        except Exception:
            return default

def _app_cache_dir() -> str:
    base = os.environ.get("APPDATA") if os.name == "nt" else os.path.join(os.path.expanduser("~"), ".config")
    root = os.path.join(base, "PlayWithAayan-ERP_Software", "cache")
    os.makedirs(root, exist_ok=True)
    return root

def _save_cache_json(filename: str, payload: dict):
    try:
        path = os.path.join(_app_cache_dir(), filename)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except Exception:
        pass

def _load_cache_json(filename: str) -> dict:
    try:
        path = os.path.join(_app_cache_dir(), filename)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _flatten_qty_rows(qty_map):
    """
    Yield (branch, color, condition, qty) from nested qty structure.

    Handles None/empty dicts and string/number quantities.
    Ensures color/condition keys are treated as strings (including 'No Color', etc.).
    """
    qty_map = qty_map or {}
    for branch, colors in qty_map.items():
        colors = colors or {}
        for color, conds in colors.items():
            conds = conds or {}
            for condition, q in conds.items():
                yield str(branch), str(color), str(condition), _safe_float(q)
                
def _fmt_dash(v, default="-"):
    s = "" if v is None else str(v).strip()
    return s if s else default

def _fmt_money(v):
    try:
        n = float(v or 0)
    except Exception:
        return "0.00"
    return f"{n:,.2f}"

def _to_value_for_mode(dc):
    mode = str(dc.get("mode", "") or "").strip().lower()
    if mode == "inventory transfer":
        return _fmt_dash(dc.get("transfer_to_branch"))
    return _fmt_dash(dc.get("delivery_location"))

def export_delivery_chalan_pdf(dc: dict, out_path: str):
    """
    Build a nicely formatted Delivery Chalan PDF (ReportLab only).
    """
    if not _HAS_REPORTLAB:
        raise RuntimeError("ReportLab not installed. Please: pip install reportlab")

    # ---------- Document ----------
    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=18*mm,
        rightMargin=18*mm,
        topMargin=16*mm,
        bottomMargin=16*mm,
        title=f"Delivery Chalan {dc.get('dc_no','')}",
        author=_fmt_dash(dc.get("created_by", "System")),
    )

    styles = getSampleStyleSheet()
    H1 = ParagraphStyle(
        "H1",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        spaceAfter=8,
        textColor=colors.HexColor("#111827"),
    )
    H2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#374151"),
        spaceBefore=8,
        spaceAfter=4,
    )
    P = ParagraphStyle(
        "P",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.3,
        leading=12,
        textColor=colors.HexColor("#111827"),
    )
    Small = ParagraphStyle(
        "Small",
        parent=P,
        fontSize=8.7,
        leading=11,
        textColor=colors.HexColor("#4B5563"),
    )

    story = []

    # ---------- Title ----------
    dc_no = _fmt_dash(dc.get("dc_no"))
    story.append(Paragraph(f"Delivery Chalan <b>{dc_no}</b>", H1))
    story.append(Spacer(0, 4))

    # ---------- Summary (2xN table) ----------
    date = _fmt_dash(dc.get("date"))
    mode = _fmt_dash(dc.get("mode"))
    from_branch = _fmt_dash(dc.get("branch"))
    to_value = _to_value_for_mode(dc)

    summary_data = [
        [Paragraph("<b>DC Number</b>", P), Paragraph(dc_no, P),
         Paragraph("<b>Date</b>", P), Paragraph(date, P)],
        [Paragraph("<b>From Branch</b>", P), Paragraph(from_branch, P),
         Paragraph("<b>Mode</b>", P), Paragraph(mode, P)],
        [Paragraph("<b>To</b>", P), Paragraph(to_value, P),
         "", ""],
    ]
    summary_tbl = Table(summary_data, colWidths=[25*mm, 65*mm, 20*mm, 62*mm])
    summary_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
        ("BOX", (0,0), (-1,-1), 0.3, colors.grey),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(summary_tbl)
    story.append(Spacer(0, 6))

    # ---------- Transport & Location ----------
    vehicle_no = _fmt_dash(dc.get("vehicle_no"))
    vehicle_person = _fmt_dash(dc.get("vehicle_person"))
    phys = str(dc.get("physical_dc_no") or "").strip()
    phys = "-" if phys in ("", "0") else phys

    tloc_data = [
        [Paragraph("<b>Vehicle No</b>", P), Paragraph(vehicle_no, P),
         Paragraph("<b>Vehicle Person</b>", P), Paragraph(vehicle_person, P)],
        [Paragraph("<b>Physical DC Number</b>", P), Paragraph(phys, P),
         "", ""],
    ]
    tloc_tbl = Table(tloc_data, colWidths=[32*mm, 55*mm, 32*mm, 53*mm])
    tloc_tbl.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.3, colors.grey),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(Paragraph("Transport & Location", H2))
    story.append(tloc_tbl)
    story.append(Spacer(0, 6))

    # ---------- Accounting ----------
    fare = _fmt_money(dc.get("delivery_fare"))
    payer_raw = str(dc.get("delivery_fare_payer") or "")
    payer = "Sender" if payer_raw == "Sender Will Pay" else ("Receiver" if payer_raw else "-")
    fare_je_id = _fmt_dash(dc.get("fare_je_id"))

    acc_data = [
        [Paragraph("<b>Delivery Fare</b>", P), Paragraph(fare, P),
         Paragraph("<b>Payer</b>", P), Paragraph(payer, P)],
        [Paragraph("<b>Fare JE Id</b>", P), Paragraph(fare_je_id, P),
         "", ""],
    ]
    acc_tbl = Table(acc_data, colWidths=[28*mm, 59*mm, 18*mm, 67*mm])
    acc_tbl.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.3, colors.grey),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(Paragraph("Accounting", H2))
    story.append(acc_tbl)
    story.append(Spacer(0, 8))

    # ---------- Items ----------
    items = dc.get("items") or []
    # Build rows
    rows = [["Sr", "Item Code", "Name (Detailed)", "Color", "Condition", "Qty"]]
    total_qty = 0.0
    for i, it in enumerate(items, start=1):
        qty = it.get("qty", 0)
        try:
            total_qty += float(qty or 0)
        except Exception:
            pass
        rows.append([
            str(i),
            _fmt_dash(it.get("item_code")),
            _fmt_dash(it.get("product_name")),
            _fmt_dash(it.get("color")),
            _fmt_dash(it.get("condition")),
            _fmt_dash(qty),
        ])

    # Column widths for A4 content area
    content_w = A4[0] - doc.leftMargin - doc.rightMargin
    col_widths = [12*mm, 22*mm, content_w - (12*mm+22*mm+22*mm+24*mm+18*mm),
                  22*mm, 24*mm, 18*mm]

    items_tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#E5E7EB")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#111827")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,0), 9.5),
        ("ALIGN", (0,0), (-1,0), "CENTER"),

        ("BOX", (0,0), (-1,-1), 0.35, colors.grey),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),

        ("ALIGN", (-1,1), (-1,-1), "RIGHT"),  # Qty right-align
        ("LEFTPADDING", (0,0), (-1,-1), 5),
        ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))

    story.append(Paragraph("Items", H2))
    story.append(items_tbl)
    story.append(Spacer(0, 4))
    story.append(Paragraph(f"<b>Items:</b> {len(items)} &nbsp;&nbsp; <b>Total Qty:</b> {(_fmt_dash(f'{total_qty:g}'))}", Small))
    story.append(Spacer(0, 8))

    # ---------- Notes ----------
    notes = str(dc.get("notes", "") or "").strip()
    if notes:
        story.append(Paragraph("Notes", H2))
        story.append(Paragraph(notes.replace("\n", "<br/>"), P))
        story.append(Spacer(0, 6))

    # ---------- Meta ----------
    created_by = _fmt_dash(dc.get("created_by") or dc.get("createdBy") or (dc.get("meta") or {}).get("created_by"))
    created_at = _fmt_dash(dc.get("created_at") or dc.get("createdAt") or dc.get("created"))
    meta_tbl = Table([
        [Paragraph("<b>Created By</b>", P), Paragraph(created_by, P),
         Paragraph("<b>Created At</b>", P), Paragraph(created_at, P)]
    ], colWidths=[22*mm, 67*mm, 22*mm, 60*mm])
    meta_tbl.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.3, colors.grey),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(Paragraph("Meta", H2))
    story.append(meta_tbl)

    # ---------- Build ----------
    doc.build(story)


# -------------------------------
# Inventory Selector (enhanced)
# -------------------------------

class InventorySelectorDialog(QDialog):
    """Select flattened inventory rows for a chosen branch. Returns list of items with quantities.

    Changes:
      - Detailed product label in Name column: "{name} - {L}{Lu}×{W}{Wu}[×{H}{Hu}] - {gauge}G"
      - Removed "Add" checkbox. On OK, any row with Qty>0 is selected.
      - LIVE FILTERING: filters apply instantly on any change (typing/selecting).
      - NEW: Accepts `preselected` mapping so reopening dialog prefills previous quantities.
    """
    def __init__(self, branch: str, preselected=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Inventory Items")
        self.setMinimumSize(1100, 650)
        self.branch = branch
        self.rows = []
        self.selected = []
        # preseed with previously selected rows (from main dialog)
        self.selection = {**(preselected or {})}  # key -> qty typed by user (preserved across filters)
        self.base_available = {}  # key -> original available
        self.row_by_key = {}  # key -> row dict for later retrieval

        v = QVBoxLayout(self)

        # Helpers for label formatting
        def _fmt_dim(x):
            try:
                x = float(x)
                if abs(x) < 1e-12:
                    return ""
                if abs(x - int(x)) < 1e-12:
                    return str(int(x))
                return str(x).rstrip('0').rstrip('.') if '.' in str(x) else str(x)
            except Exception:
                return ""

        def _unit_disp(u: str) -> str:
            u = (u or "").strip()
            if u.lower() in ("inch", "inches", 'in'):
                return '"'
            if u.lower() in ("ft", "feet", "foot"):
                return "'"
            return u  # keep MM etc.

        self._fmt_dim = _fmt_dim
        self._unit_disp = _unit_disp

        # Filters
        filt_box = QGroupBox("Filters")
        grid = QGridLayout(filt_box)

        self.search = QLineEdit(); self.search.setPlaceholderText("Free text: branch, name, code, color, condition…")
        self.f_len = QLineEdit(); self.f_len.setPlaceholderText("Length")
        self.f_wid = QLineEdit(); self.f_wid.setPlaceholderText("Width")
        self.f_hei = QLineEdit(); self.f_hei.setPlaceholderText("Height")
        self.f_gau = QLineEdit(); self.f_gau.setPlaceholderText("Gauge")

        self.f_color = QComboBox(); self.f_color.addItem("Any")
        self.f_cond  = QComboBox(); self.f_cond.addItem("Any")

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._clear_filters)

        grid.addWidget(QLabel("Search"), 0, 0); grid.addWidget(self.search, 0, 1, 1, 6)
        grid.addWidget(QLabel("Length"), 1, 0); grid.addWidget(self.f_len, 1, 1)
        grid.addWidget(QLabel("Width"), 1, 2); grid.addWidget(self.f_wid, 1, 3)
        grid.addWidget(QLabel("Height"), 1, 4); grid.addWidget(self.f_hei, 1, 5)
        grid.addWidget(QLabel("Gauge"), 1, 6); grid.addWidget(self.f_gau, 1, 7)
        grid.addWidget(QLabel("Color"), 2, 0); grid.addWidget(self.f_color, 2, 1, 1, 3)
        grid.addWidget(QLabel("Condition"), 2, 4); grid.addWidget(self.f_cond, 2, 5, 1, 3)
        grid.addWidget(btn_clear, 0, 7)

        v.addWidget(filt_box)

        # Live wiring
        self.search.textChanged.connect(self._apply_filter)
        self.f_len.textChanged.connect(self._apply_filter)
        self.f_wid.textChanged.connect(self._apply_filter)
        self.f_hei.textChanged.connect(self._apply_filter)
        self.f_gau.textChanged.connect(self._apply_filter)
        self.f_color.currentIndexChanged.connect(self._apply_filter)
        self.f_cond.currentIndexChanged.connect(self._apply_filter)

        # Table
        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels(["Branch", "Item Code", "Name", "Color", "Condition", "Available", "Qty to Deliver"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        # NEW: make all table cells read-only; Qty stays editable because it's a QLineEdit cell widget
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        v.addWidget(self.tbl)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._collect_and_accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        self._load_inventory()

    def _make_label(self, it):
        L = self._fmt_dim(it.get("length"))
        W = self._fmt_dim(it.get("width"))
        H = self._fmt_dim(it.get("height"))
        Lu = self._unit_disp(it.get("length_unit"))
        Wu = self._unit_disp(it.get("width_unit"))
        Hu = self._unit_disp(it.get("height_unit"))
        size = f"{L}{Lu}×{W}{Wu}"
        if H:
            size += f"×{H}{Hu}"
        return f"{it.get('name','')} - {size} - {self._fmt_dim(it.get('gauge'))}G"

    def _load_inventory(self):
        self.rows.clear()
        want_branch = (self.branch or "").strip() or None

        color_values = set()
        cond_values = set()

        for snap in db.collection("products").stream():
            d = snap.to_dict() or {}
            item_code = (d.get("item_code") or "").strip()
            name = (d.get("name") or "Unnamed").strip()

            length = _safe_float(d.get("length"))
            width  = _safe_float(d.get("width"))
            height = _safe_float(d.get("height"))
            gauge  = _safe_float(d.get("gauge"))
            length_unit = str(d.get("length_unit") or "").strip()
            width_unit  = str(d.get("width_unit") or "").strip()
            height_unit = str(d.get("height_unit") or "").strip()

            qty_map = d.get("qty") or {}
            for branch, color, cond, av in _flatten_qty_rows(qty_map):
                if want_branch and branch != want_branch:
                    continue
                color_values.add(color)
                cond_values.add(cond)
                row = {
                    "product_id": snap.id,
                    "branch": branch,

                    "item_code": item_code,
                    "name": name,
                    "color": color,
                    "condition": cond,
                    "available": av,
                    "length": length, "width": width, "height": height, "gauge": gauge,
                    "length_unit": length_unit, "width_unit": width_unit, "height_unit": height_unit,
                }
                row["detailed_label"] = self._make_label(row)
                self.rows.append(row)
                key = f"{branch}|{item_code}|{color}|{cond}"
                self.base_available[key] = av
                self.row_by_key[key] = row

        # populate combos
        for c in sorted(color_values):
            self.f_color.addItem(c)
        for c in sorted(cond_values):
            self.f_cond.addItem(c)

        self._render_rows(self.rows)  # selections preserved; avail recalculated per row

    def _render_rows(self, rows):
        self.tbl.setRowCount(len(rows))
        for r, it in enumerate(rows):
            key = f"{it['branch']}|{it['item_code']}|{it['color']}|{it['condition']}"
            sel_q = self.selection.get(key, 0.0)
            base_av = self.base_available.get(key, it.get('available', 0.0))
            live_av = max(0.0, float(base_av) - float(sel_q))

            # Cells
            self.tbl.setItem(r, 0, QTableWidgetItem(it['branch']))
            item_code_cell = QTableWidgetItem(it['item_code'])
            item_code_cell.setData(Qt.UserRole, key)
            self.tbl.setItem(r, 1, item_code_cell)
            self.tbl.setItem(r, 2, QTableWidgetItem(it['detailed_label']))
            self.tbl.setItem(r, 3, QTableWidgetItem(it['color']))
            self.tbl.setItem(r, 4, QTableWidgetItem(it['condition']))
            self.tbl.setItem(r, 5, QTableWidgetItem(f"{live_av:g}"))

            qty_str = (str(int(sel_q)) if abs(sel_q - int(sel_q)) < 1e-12 else str(sel_q)) if sel_q else "0"
            qty = QLineEdit(qty_str)
            qty.textChanged.connect(lambda text, k=key: self._on_qty_changed(k, text))
            self.tbl.setCellWidget(r, 6, qty)

    def _on_qty_changed(self, key, text):
        # Parse, clamp to >=0; do not mutate text to avoid cursor jumps
        q = 0.0
        try:
            q = float(text) if str(text).strip() else 0.0
        except Exception:
            q = 0.0
        if q < 0:
            q = 0.0
        self.selection[key] = q
        # Update the 'Available' cell live
        base_av = self.base_available.get(key, 0.0)
        live_av = max(0.0, float(base_av) - float(q))
        # Find the row with this key
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 1)
            if it and it.data(Qt.UserRole) == key:
                av_item = self.tbl.item(r, 5)
                if av_item:
                    av_item.setText(f"{live_av:g}")
                break

    def _clear_filters(self):
        self.search.clear()
        self.f_len.clear(); self.f_wid.clear(); self.f_hei.clear(); self.f_gau.clear()
        self.f_color.setCurrentIndex(0); self.f_cond.setCurrentIndex(0)
        self._render_rows(self.rows)

    def _apply_filter(self):
        term = (self.search.text() or "").lower().strip()
        want_len = self.f_len.text().strip()
        want_wid = self.f_wid.text().strip()
        want_hei = self.f_hei.text().strip()
        want_gau = self.f_gau.text().strip()
        want_color = self.f_color.currentText()
        want_cond = self.f_cond.currentText()

        def match_num(filter_text, value):
            if not filter_text:
                return True
            try:
                return abs(float(filter_text) - float(value)) < 1e-9
            except Exception:
                return filter_text.lower() in str(value).lower()

        filtered = []
        for it in self.rows:
            if want_color != "Any" and it["color"] != want_color:
                continue
            if want_cond != "Any" and it["condition"] != want_cond:
                continue
            if not match_num(want_len, it["length"]):
                continue
            if not match_num(want_wid, it["width"]):
                continue
            if not match_num(want_hei, it["height"]):
                continue
            if not match_num(want_gau, it["gauge"]):
                continue

            if term:
                hay = " ".join([it["branch"], it["item_code"], it["name"], it["color"], it["condition"], it["detailed_label"]]).lower()
                if term not in hay:
                    continue
            filtered.append(it)

        self._render_rows(filtered)

    def _collect_and_accept(self):
        items = []
        # Validate selections against base availability
        for key, qty in self.selection.items():
            qty = float(qty or 0)
            if qty <= 0:
                continue
            base_av = float(self.base_available.get(key, 0.0))
            if qty > base_av + 1e-9:
                # Find label for friendly message
                row = self.row_by_key.get(key, {})
                branch, code, color, cond = key.split('|')
                QMessageBox.warning(self, 'Qty too high', f"[{branch}] {code} / {color} / {cond}: Qty {qty:g} exceeds available {base_av:g}. Reduce it.")
                return
        # Build items list
        for key, qty in self.selection.items():
            qty = float(qty or 0)
            if qty <= 0:
                continue
            row = self.row_by_key.get(key, {})
            if not row:
                continue
            items.append({
                'branch': row.get('branch',''),
                'item_code': row.get('item_code',''),
                'product_name': row.get('detailed_label','') or row.get('name',''),
                'color': row.get('color',''),
                'condition': row.get('condition',''),
                'qty': qty,
            })
        if not items:
            QMessageBox.warning(self, 'No items', 'Enter quantity (> 0) for at least one row.')
            return
        self.selected = items
        self.accept()

# -------------------------------
# Delivery chalan form
# -------------------------------
class DeliveryChalanForm(QDialog):
    """Create a delivery chalan"""
    
    def _peek_next_dc_number(self) -> str:
        """
        Return a non-reserved preview of the next DC number (best-effort).
        Note: This is a preview only; the actual assigned number is reserved atomically on Save.
        """
        try:
            meta_ref = db.collection("meta").document("delivery_chalan_counter")
            snap = meta_ref.get()
            last = int((snap.get("last_number") if snap.exists else 0) or 0)
            nxt = last + 1
            return f"DC-{nxt:06d}"
        except Exception:
            # Fallback when offline or meta is missing
            return "DC-(preview)"
    
    def _on_mode_change(self):
        mode = self.mode_cb.currentText()
        is_transfer = (mode == "Inventory Transfer")
        self.delivery_location.setVisible(not is_transfer)
        self.dest_branch_cb.setVisible(is_transfer)
        if is_transfer and self.dest_branch_cb.count() > 0:
            src = self.branch_cb.currentText().strip()
            for i in range(self.dest_branch_cb.count()):
                if self.dest_branch_cb.itemText(i) != src:
                    self.dest_branch_cb.setCurrentIndex(i)
                    break

    def _list_admin_branches(self):
        branches = []
        try:
            snap = db.collection("admin").document("settings").get()
            if snap.exists:
                arr = snap.to_dict().get("branches") or []
                if isinstance(arr, list):
                    branches.extend([str(x) for x in arr if str(x).strip()])
        except Exception:
            pass
        if not branches:
            try:
                seen = set()
                for s in db.collection("products").limit(2000).stream():
                    d = s.to_dict() or {}
                    for br in (d.get("qty") or {}).keys():
                        if br and br not in seen:
                            seen.add(br)
                branches = sorted(seen)
            except Exception:
                pass
        if not branches:
            try:
                branches = self.user_data.get("all_branches") or self.user_data.get("branch") or []
                if isinstance(branches, str):
                    branches = [branches]
                branches = [b for b in branches if str(b).strip()]
            except Exception:
                pass
        return list(dict.fromkeys(branches))
    
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Delivery Chalan")
        self.setMinimumSize(1100, 650)  # tweak #1
        self.user_data = user_data
        self.items = []

        self.setStyleSheet(APP_STYLE)

        v = QVBoxLayout(self)
        # Top meta
        meta_box = QGroupBox("Delivery Chalan Info")
        form = QFormLayout(meta_box)

        self.dc_no_preview = QLineEdit(); self.dc_no_preview.setReadOnly(True)
        self.dc_no_preview.setText(self._peek_next_dc_number())

        self.phys_dc_no = QLineEdit(); self.phys_dc_no.setPlaceholderText("0 = No Physical DC Made")
        self.date_edit = QDateEdit(QDate.currentDate()); self.date_edit.setCalendarPopup(True)

        # Branch selection (explicit)
        branches = self.user_data.get("branch")
        if isinstance(branches, str):
            branches = [branches] if branches else []
        branches = branches or []
        self.branch_cb = QComboBox(); self.branch_cb.addItems(branches if branches else ["-"])
        
        # NEW: clear current selected items when branch changes
        self.branch_cb.currentIndexChanged.connect(self._on_branch_changed)

        self.vehicle_no = QLineEdit()
        self.vehicle_person_cb = QComboBox()
        self.vehicle_person_cb.setEditable(True)  # allow quick type-to-filter
        self._load_vehicle_person_accounts() 
        # Mode + destination/location controls
        self.mode_cb = QComboBox(); self.mode_cb.addItems(["Chalan", "Inventory Transfer"])
        self.delivery_location = QLineEdit(); self.delivery_location.setPlaceholderText("Where will items be delivered?")
        self.dest_branch_cb = QComboBox(); self.dest_branch_cb.setVisible(False)
        try:
            for b in self._list_admin_branches():
                self.dest_branch_cb.addItem(b)
        except Exception:
            pass
        self.mode_cb.currentIndexChanged.connect(self._on_mode_change)
        self.notes = QTextEdit()
        
        # Delivery Fare + Payer
        self.delivery_fare_edit = QLineEdit()
        self.delivery_fare_edit.setPlaceholderText("0.00")
        self.delivery_fare_payer_cb = QComboBox()
        self.delivery_fare_payer_cb.addItems(["Sender Will Pay", "Receiver Will Pay"])

        fare_row = QHBoxLayout()
        fare_wrap = QWidget(); fare_wrap.setLayout(fare_row)
        fare_row.addWidget(self.delivery_fare_edit)
        fare_row.addSpacing(8)
        fare_row.addWidget(self.delivery_fare_payer_cb)


        form.addRow("DC Number", self.dc_no_preview)
        form.addRow("Physical DC Number", self.phys_dc_no)
        form.addRow("Date", self.date_edit)
        form.addRow("From Branch", self.branch_cb)
        form.addRow("Vehicle Number", self.vehicle_no)
        form.addRow("Vehicle Person", self.vehicle_person_cb)
        form.addRow("Delivery Fare", fare_wrap)
        loc_row = QHBoxLayout(); loc_wrap = QWidget(); loc_wrap.setLayout(loc_row)
        loc_row.addWidget(self.mode_cb)
        loc_row.addSpacing(8)
        loc_row.addWidget(self.delivery_location)
        loc_row.addWidget(self.dest_branch_cb)
        form.addRow("Delivery / Transfer To", loc_wrap)
        form.addRow("Additional Notes", self.notes)

        v.addWidget(meta_box)

        # Items box
        items_box = QGroupBox("Items")
        il = QVBoxLayout(items_box)

        top_row = QHBoxLayout()
        self.info_label = QLabel("Select items from inventory for this branch.")
        self.btn_select = QPushButton("Select Items…")
        self.btn_select.clicked.connect(self._open_selector)
        top_row.addWidget(self.info_label)
        top_row.addStretch()
        top_row.addWidget(self.btn_select)
        il.addLayout(top_row)

        # Items table (selected items)
        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(["Item Code", "Name", "Color", "Condition", "Qty to Deliver"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        # NEW: make main table read-only
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        il.addWidget(self.tbl)

        v.addWidget(items_box)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        # Initialize mode-based visibility
        try:
            self._on_mode_change()
        except Exception:
            pass
        
    def _on_branch_changed(self):
        # Clear the main item section when the source branch changes
        self.items = []
        self._render_items()

    def _render_items(self):
        self.tbl.setRowCount(len(self.items))
        for i, it in enumerate(self.items):
            for col, val in enumerate([
                it.get("item_code",""),
                it.get("product_name",""),
                it.get("color",""),
                it.get("condition",""),
                str(it.get("qty", 0)),
            ]):
                item = QTableWidgetItem(val)
                # ensure per-cell read-only
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.tbl.setItem(i, col, item)

    def _open_selector(self):
        branch = self.branch_cb.currentText().strip() or "-"

        # Build preselected mapping so reopening the selector shows current quantities
        preselected = {}
        for it in (self.items or []):
            key = f"{branch}|{it.get('item_code','')}|{it.get('color','')}|{it.get('condition','')}"
            preselected[key] = _safe_float(it.get("qty", 0))

        dlg = InventorySelectorDialog(branch=branch, preselected=preselected, parent=self)
        if dlg.exec_():
            # OVERWRITE semantics:
            # Use only what the selector returns; for duplicate keys in the dialog
            # (shouldn't happen), the last occurrence wins.
            by_key = {}
            for it in dlg.selected:
                code = it.get("item_code", "")
                color = it.get("color", "")
                cond = it.get("condition", "")
                qty = _safe_float(it.get("qty", 0))
                key = (code, color, cond)
                by_key[key] = {
                    "item_code": code,
                    "product_name": it.get("product_name", ""),
                    "color": color,
                    "condition": cond,
                    "qty": qty,
                }

            # Replace (don’t add to) existing items
            self.items = list(by_key.values())
            self._render_items()
            
    def _load_vehicle_person_accounts(self):
        """
        Populate vehicle_person_cb with Employee-linked accounts first.
        Fallback: Liability accounts (prefer slugs like 'emp_*').
        """
        self.vehicle_person_cb.clear()

        # 1) Try employees (Active first), using their COA account ids
        try:
            emp_stream = db.collection("employees").select([
                "name", "employee_code", "status", "coa_account_id"
            ]).stream()
        except Exception:
            emp_stream = db.collection("employees").stream()

        employees = []
        for doc in emp_stream:
            e = doc.to_dict() or {}
            name = (e.get("name") or "").strip()
            code = (e.get("employee_code") or "").strip()
            status = (e.get("status") or "Active").strip()
            coa_id = (e.get("coa_account_id") or "").strip()
            if not coa_id or not name:
                continue
            display = f"{name} [{code}]" if code else name
            # Prefer Active employees at the top
            employees.append((0 if status.lower() == "active" else 1, display, coa_id, name))

        employees.sort(key=lambda t: (t[0], t[1].lower()))
        for _rank, display, coa_id, name in employees:
            self.vehicle_person_cb.addItem(display, userData={"account_id": coa_id, "name": name})

        if self.vehicle_person_cb.count() > 0:
            return  # Employees found; good to go

        # 2) Fallback to Liability accounts (prefer slugs like 'emp_*' if available)
        try:
            acc_stream = db.collection("accounts").where("type", "==", "Liability").stream()
        except Exception:
            acc_stream = []

        empish, others = [], []
        for a in acc_stream:
            d = a.to_dict() or {}
            name = (d.get("name") or "").strip() or a.id
            slug = (d.get("slug") or "").strip().lower()
            code = str(d.get("code") or "").strip()
            display = f"{name} [{code}]" if code else name
            payload = {"account_id": a.id, "name": name}
            if slug.startswith("emp_"):
                empish.append((display.lower(), display, payload))
            else:
                others.append((display.lower(), display, payload))

        # Prioritize likely employee sub-accounts (‘emp_*’)
        for _, display, payload in sorted(empish):
            self.vehicle_person_cb.addItem(display, userData=payload)
        for _, display, payload in sorted(others):
            self.vehicle_person_cb.addItem(display, userData=payload)

        if self.vehicle_person_cb.count() == 0:
            # Last resort: at least add a blank option
            self.vehicle_person_cb.addItem("(no accounts found)", userData={"account_id": "", "name": ""})


    # --- DC number reservation (on save) ---
    def _reserve_dc_number(self) -> str:
        """
        Reserve the next DC number atomically from meta/delivery_chalan_counter.
        Returns the formatted DC number (e.g., 'DC-000123').
        """
        meta_ref = db.collection("meta").document("delivery_chalan_counter")
        try:
            if not meta_ref.get().exists:
                meta_ref.set({"last_number": 0})
        except Exception:
            pass

        transaction = firestore.client().transaction()

        @firestore.transactional
        def _incr_tx(trans):
            snap = meta_ref.get(transaction=trans)
            last = int((snap.get("last_number") if snap.exists else 0) or 0)
            new = last + 1
            trans.set(meta_ref, {"last_number": new}, merge=True)
            return new

        try:
            nxt = _incr_tx(transaction)
        except Exception:
            # Fallback: timestamp-based unique-ish id
            nxt = int(datetime.datetime.now().strftime("%y%m%d%H%M%S"))
        return f"DC-{nxt:06d}"

    def _save(self):
        if not self.items:
            QMessageBox.warning(self, "Missing Items", "Please select at least one item.")
            return

        # Source branch
        branch = (self.branch_cb.currentText() or "").strip() or "-"

        # 1) Reserve DC number now and show preview (assignment happens here)
        dc_number = self._reserve_dc_number()
        try:
            self.dc_no_preview.setText(dc_number)
        except Exception:
            pass

        # 2) Physical DC number (optional integer)
        phys_text = (self.phys_dc_no.text() or "").strip()
        try:
            physical_dc_no = int(phys_text) if phys_text else 0
        except Exception:
            physical_dc_no = 0

        # 3) Canonicalize mode and destination branch ONCE
        mode = (self.mode_cb.currentText() or "").strip()  # "Chalan" or "Inventory Transfer"
        dest_branch = ""
        if mode == "Inventory Transfer":
            dest_branch = (self.dest_branch_cb.currentText() or "").strip() if self.dest_branch_cb.isVisible() else ""
            if not dest_branch:
                QMessageBox.warning(self, "Destination Missing", "Please select a destination branch for the transfer.")
                return
            if dest_branch == branch:
                QMessageBox.warning(self, "Invalid Destination", "Destination branch must be different from the source branch.")
                return

        # 4) Delivery location text (hidden/ignored for transfers)
        delivery_location_text = "" if mode == "Inventory Transfer" else (self.delivery_location.text() or "").strip()

        # 5) Vehicle Person from dropdown (account-linked)
        vp_data = self.vehicle_person_cb.currentData() or {}
        vehicle_person_name = (vp_data.get("name") or self.vehicle_person_cb.currentText() or "").strip()
        vehicle_person_account_id = (vp_data.get("account_id") or "").strip()

        # 6) Delivery Fare (+ payer) — VALIDATION: required iff Sender Will Pay
        fare_text = (self.delivery_fare_edit.text() or "0").replace(",", "").strip()
        try:
            delivery_fare = float(fare_text)
        except Exception:
            delivery_fare = 0.0
        delivery_fare_payer = (self.delivery_fare_payer_cb.currentText() or "").strip()  # "Sender Will Pay" | "Receiver Will Pay"

        if delivery_fare_payer == "Sender Will Pay":
            if delivery_fare <= 0:
                QMessageBox.warning(self, "Delivery Fare Required", "Enter a positive Delivery Fare when 'Sender Will Pay' is selected.")
                return
            if not vehicle_person_account_id:
                QMessageBox.warning(self, "Vehicle Person Required", "Select a Vehicle Person/Employee account for 'Sender Will Pay'.")
                return

        # 7) Build payload (include fields the detail dialog expects)
        payload = {
            "dc_no": dc_number,
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "branch": branch,

            "vehicle_no": (self.vehicle_no.text() or "").strip(),
            "vehicle_person": vehicle_person_name,
            "vehicle_person_account_id": vehicle_person_account_id,

            "delivery_fare": delivery_fare,
            "delivery_fare_payer": delivery_fare_payer,

            "delivery_location": delivery_location_text,
            "notes": (self.notes.toPlainText() or "").strip(),
            "physical_dc_no": physical_dc_no,
            "items": self.items,
            "created_at": firestore.SERVER_TIMESTAMP,
            "created_by": str((self.user_data or {}).get("name", "")).strip().lower(),

            "mode": mode,
            "transfer_to_branch": dest_branch,
        }

        # 8) Save chalan
        chalan_ref = db.collection("delivery_chalans").document()
        chalan_ref.set(payload)

        # 9) Inventory adjustments
        for it in self.items:
            code = it.get("item_code", ""); color = it.get("color", ""); cond = it.get("condition", "")
            qty = _safe_float(it.get("qty", 0))
            if not code or qty <= 0:
                continue
            try:
                qdocs = db.collection("products").where("item_code", "==", code).limit(1).get()
                if not qdocs:
                    continue
                pd = qdocs[0]; pobj = pd.to_dict() or {}
                qty_dict = pobj.get("qty") or {}

                # Decrement from source branch/color/condition
                try:
                    qty_dict.setdefault(branch, {})
                    qty_dict[branch].setdefault(color, {})
                    prev = _safe_float(qty_dict[branch][color].get(cond, 0))
                    qty_dict[branch][color][cond] = max(0.0, prev - qty)
                    db.collection("products").document(pd.id).update({"qty": qty_dict})
                except Exception as e1:
                    print("Inventory decrement failed for", code, color, cond, ":", e1)

                # Inventory Transfer: increment destination branch
                if mode == "Inventory Transfer" and dest_branch and dest_branch != branch:
                    try:
                        qty_dict.setdefault(dest_branch, {})
                        qty_dict[dest_branch].setdefault(color, {})
                        prev_to = _safe_float(qty_dict[dest_branch][color].get(cond, 0))
                        qty_dict[dest_branch][color][cond] = prev_to + qty
                        db.collection("products").document(pd.id).update({"qty": qty_dict})
                    except Exception as e2:
                        print("Inventory increment (transfer) failed for", code, color, cond, ":", e2)
            except Exception as e:
                print("Inventory product fetch failed for", code, ":", e)

        # 10) If Sender Will Pay → create JE (Credit Employee/Vehicle Person, Debit Opening Balances Equity)
        #     — with balance_before snapshots and atomic balance bumps (matches journal_entry.py).
        if delivery_fare_payer == "Sender Will Pay" and delivery_fare > 0 and vehicle_person_account_id:
            try:
                # Find or create Opening Balances Equity (type **Equity**)
                eq_q = db.collection("accounts").where("slug", "==", "opening_balances_equity").limit(1).get()
                if eq_q:
                    equity_id = eq_q[0].id
                    eq_doc = eq_q[0].to_dict() or {}
                    equity_name = eq_doc.get("name", "System Offset Account")
                    equity_type = eq_doc.get("type", "Asset")
                else:
                    from re import sub as _re_sub
                    def _generate_code_once(acc_type):
                        prefix = {"Asset":"1","Liability":"2","Equity":"3","Income":"4","Expense":"5"}.get(acc_type, "9")
                        counter_ref = db.collection("meta").document("account_code_counters")
                        transaction = firestore.client().transaction()
                        @firestore.transactional
                        def increment_code(trans):
                            snapshot = counter_ref.get(transaction=trans)
                            data = snapshot.to_dict() or {}
                            last = data.get(acc_type)
                            if not last:
                                query = db.collection("accounts").where("type", "==", acc_type).get()
                                codes = []
                                for d in query:
                                    code_str = str((d.to_dict() or {}).get("code", ""))
                                    if code_str.startswith(prefix):
                                        try: codes.append(int(code_str))
                                        except: pass
                                last = max(codes) if codes else int(prefix + "000")
                            new_code = int(last) + 1
                            data[acc_type] = new_code
                            trans.set(counter_ref, data, merge=True)
                            return str(new_code)
                        return increment_code(transaction)

                    code = _generate_code_once("Asset")
                    branch_list = self.user_data.get("branch", [])
                    if isinstance(branch_list, str): branch_list = [branch_list]
                    equity_doc = {
                        "name": "System Offset Account",
                        "slug": "opening_balances_equity",
                        "type": "Asset",
                        "code": code,
                        "parent": None,
                        "branch": branch_list,
                        "description": "System-generated equity account for opening balances",
                        "active": True,
                        "is_posting": True,
                        "opening_balance": None,
                        "current_balance": 0.0
                    }
                    ref = db.collection("accounts").document()
                    ref.set(equity_doc)
                    equity_id = ref.id
                    equity_name = "System Offset Account"
                    equity_type = "Asset"

                # Fetch current balances / types for both accounts (to set balance_before & compute net)
                # Vehicle/employee account
                try:
                    vp_snap = db.collection("accounts").document(vehicle_person_account_id).get()
                    vp_doc = vp_snap.to_dict() or {}
                    vp_type = (vp_doc.get("type") or "Liability")  # employees are usually Liability sub-accounts
                    vp_pre = float(vp_doc.get("current_balance", 0.0) or 0.0)
                except Exception:
                    vp_type = "Liability"
                    vp_pre = 0.0

                # Equity account pre-balance
                try:
                    eq_snap = db.collection("accounts").document(equity_id).get()
                    eq_doc2 = eq_snap.to_dict() or {}
                    eq_pre = float(eq_doc2.get("current_balance", 0.0) or 0.0)
                except Exception:
                    eq_pre = 0.0

                # Build JE lines (Sender Will Pay: Credit Employee, Debit Equity)
                debit_line = {
                    "account_id": equity_id,
                    "account_name": equity_name,
                    "debit": delivery_fare,
                    "credit": 0.0,
                    "balance_before": 0,
                }
                credit_line = {
                    "account_id": vehicle_person_account_id,
                    "account_name": vehicle_person_name or "Vehicle Person",
                    "debit": 0.0,
                    "credit": delivery_fare,
                    "balance_before": vp_pre,
                }

                # Net changes per journal_entry.py rules:
                # For Asset/Expense: net = debit - credit; else (Liability/Equity/Income): net = credit - debit
                def _net_change(acc_type, debit, credit):
                    return (debit - credit) if acc_type in ["Asset", "Expense"] else (credit - debit)

                eq_net = _net_change(equity_type, debit_line["debit"], debit_line["credit"])
                vp_net = _net_change(vp_type, credit_line["debit"], credit_line["credit"])

                # JE header — use the UI date as a proper datetime (like journal_entry.py)
                date_py = self.date_edit.date().toPyDate()
                je_date = datetime.datetime.combine(date_py, datetime.datetime.min.time())
                branch_val = self.user_data.get("branch")
                branch_val = (branch_val[0] if isinstance(branch_val, list) and branch_val else branch_val) or branch

                je = {
                    "date": je_date,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "created_by": self.user_data.get("email", "system"),
                    "reference_no": f"JE-DC-{dc_number}",
                    "purpose": "Delivery Fare",
                    "branch": branch_val,
                    "description": f"Delivery Fare for {dc_number}",
                    "lines": [debit_line, credit_line],
                    "lines_account_ids": [debit_line["account_id"], credit_line["account_id"]],
                    "meta": {"kind": "opening_balance", "dc_no": dc_number}
                }

                # Atomically create JE + bump balances for both accounts
                batch = db.batch()
                je_ref = db.collection("journal_entries").document()
                batch.set(je_ref, je)
                batch.update(db.collection("accounts").document(vehicle_person_account_id),
                            {"current_balance": firestore.Increment(vp_net)})
                batch.commit()

                # Link the JE back to this DC
                chalan_ref.update({"fare_je_id": je_ref.id})

            except Exception as e:
                # Non-fatal: DC already saved; just inform user
                print("Failed to post Delivery Fare JE:", e)
                QMessageBox.warning(
                    self,
                    "Saved with warning",
                    f"Chalan {dc_number} saved, but the Delivery Fare journal entry could not be posted.\n{e}"
                )

        QMessageBox.information(self, "Saved", f"Delivery Chalan {dc_number} created and inventory updated.")
        self.accept()




# -------------------------------
# Detail dialog
# -------------------------------
class DeliveryChalanDetailDialog(QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Delivery Chalan - {data.get('dc_no','')}")
        self.setMinimumSize(1100, 1000)
        self.setStyleSheet(APP_STYLE)
        
        self._dc_data = data

        v = QVBoxLayout(self)

        # ---- SUMMARY (top band) ----
        summary = QGroupBox("Summary")
        g = QGridLayout(summary)

        def ro(text):
            le = QLineEdit(text); le.setReadOnly(True); return le

        dc_no = ro(str(data.get("dc_no", "")))
        date  = ro(str(data.get("date", "")))
        branch = ro(str(data.get("branch", "")))
        mode_text = str(data.get("mode", "") or "")
        mode_le   = ro(mode_text)

        g.addWidget(QLabel("DC Number"), 0, 0); g.addWidget(dc_no, 0, 1)
        g.addWidget(QLabel("Date"),      0, 2); g.addWidget(date, 0, 3)
        g.addWidget(QLabel("From Branch"),1, 0); g.addWidget(branch, 1, 1)
        g.addWidget(QLabel("Mode"),       1, 2); g.addWidget(mode_le, 1, 3)

        v.addWidget(summary)

        # ---- TRANSPORT & LOCATION ----
        tbox = QGroupBox("Transport  Location")
        tf = QFormLayout(tbox)

        vehicle_no_le     = ro(str(data.get("vehicle_no","")))
        vehicle_person_le = ro(str(data.get("vehicle_person","")))

        # Create explicit label+field widgets so we can hide/show rows cleanly
        self.location_lbl = QLabel("Delivery Location")
        self.location_le  = ro(str(data.get("delivery_location","")))

        self.transfer_lbl = QLabel("Transfer To (Branch)")
        self.transfer_le  = ro(str(data.get("transfer_to_branch","")))

        tf.addRow("Vehicle No",     vehicle_no_le)
        tf.addRow("Vehicle Person", vehicle_person_le)
        tf.addRow(self.location_lbl, self.location_le)
        tf.addRow(self.transfer_lbl, self.transfer_le)

        tbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        v.addWidget(tbox)

        # Toggle visibility based on Mode
        is_transfer = (mode_text.strip().lower() == "inventory transfer")
        is_chalan   = not is_transfer  # treat any non-transfer as Chalan

        self.location_lbl.setVisible(is_chalan)
        self.location_le.setVisible(is_chalan)

        self.transfer_lbl.setVisible(is_transfer)
        self.transfer_le.setVisible(is_transfer)


        # ---- ACCOUNTING ----
        abox = QGroupBox("Accounting")
        ag = QGridLayout(abox)

        fare = float(data.get("delivery_fare", 0.0) or 0.0)
        payer = str(data.get("delivery_fare_payer","") or "")
        fare_le  = ro(f"{fare:,.2f}")
        payer_le = ro(payer)

        ag.addWidget(QLabel("Delivery Fare"), 0, 0); ag.addWidget(fare_le, 0, 1)
        ag.addWidget(QLabel("Payer"),         0, 2); ag.addWidget(payer_le, 0, 3)
        ag.addWidget(QLabel("Physical DC Number"), 1, 0); ag.addWidget(ro(str(data.get("physical_dc_no", 0) or 0)), 1, 1)

        # Link to JE if we have it
        fare_je_id = str(data.get("fare_je_id","") or "")
        ag.addWidget(QLabel("Fare JE Id"), 1, 2); ag.addWidget(ro(fare_je_id), 1, 3)

        v.addWidget(abox)

        # ---- NOTES ----
        nbox = QGroupBox("Notes")
        nf = QFormLayout(nbox)
        te = QTextEdit(); te.setReadOnly(True); te.setPlainText(str(data.get("notes","")))
        te.setMaximumHeight(120)  # 👈 keep notes compact
        nbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # 👈 don't grow vertically
        nf.addRow(te)
        v.addWidget(nbox)

        # ---- ITEMS TABLE ----
        items = data.get("items") or []
        total_qty = sum(float(it.get("qty", 0) or 0) for it in items)
        tbl = QTableWidget(0, 5)
        tbl.setHorizontalHeaderLabels(["Item Code", "Name (Detailed)", "Color", "Condition", "Qty"])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        tbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)  # 👈 expand to fill
        tbl.setMinimumHeight(240)  # 👈 give it more room
        tbl.setRowCount(len(items))
        for i, it in enumerate(items):
            tbl.setItem(i, 0, QTableWidgetItem(str(it.get("item_code",""))))
            tbl.setItem(i, 1, QTableWidgetItem(str(it.get("product_name",""))))
            tbl.setItem(i, 2, QTableWidgetItem(str(it.get("color",""))))
            tbl.setItem(i, 3, QTableWidgetItem(str(it.get("condition",""))))
            tbl.setItem(i, 4, QTableWidgetItem(str(it.get("qty",""))))
        v.addWidget(tbl)

        # Totals strip
        totals = QHBoxLayout()
        totals_lbl = QLabel(f"Items: {len(items)}    Total Qty: {total_qty:g}")
        totals_lbl.setStyleSheet("color:#374151; font-weight:600; padding:6px 2px;")
        totals.addWidget(totals_lbl); totals.addStretch()
        v.addLayout(totals)

        # ---- META (optional; only if present) ----
        created_by  = str((data.get("created_by") or data.get("created", "null")) or "null")
        created_at  = str(data.get("created_at") or "")
        meta = QGroupBox("Meta")
        mg = QGridLayout(meta)
        mg.addWidget(QLabel("Created By"), 0, 0); mg.addWidget(ro(created_by), 0, 1)
        mg.addWidget(QLabel("Created At"), 0, 2); mg.addWidget(ro(created_at), 0, 3)
        v.addWidget(meta)

        # Close + Save PDF buttons
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btn_pdf = QPushButton("Save PDF…")
        btns.addButton(btn_pdf, QDialogButtonBox.ActionRole)
        btn_pdf.clicked.connect(self._on_save_pdf_clicked)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)
        
        # Close
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)
        
    def _on_save_pdf_clicked(self):
        if not _HAS_REPORTLAB:
            QMessageBox.critical(self, "ReportLab missing",
                                "ReportLab is required to export PDF.\n\nInstall with:\n    pip install reportlab")
            return

        suggested = f"DeliveryChalan_{self._dc_data.get('dc_no','')}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Delivery Chalan as PDF", suggested, "PDF Files (*.pdf)"
        )
        if not path:
            return
        try:
            export_delivery_chalan_pdf(self._dc_data, path)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", f"Could not export PDF:\n{e}")
            return
        QMessageBox.information(self, "Done", "PDF saved successfully.")



# -------------------------------
# FASTNESS: threaded loader + cache-first paint
# -------------------------------
class _DCsLoader(QThread):
    loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def run(self):
        try:
            rows = []
            snaps = db.collection("delivery_chalans").order_by("created_at", direction=firestore.Query.DESCENDING).limit(500).stream()
            for s in snaps:
                d = s.to_dict() or {}
                d["_doc_id"] = s.id
                rows.append(d)
            self.loaded.emit(rows)
        except Exception as e:
            self.failed.emit(str(e))

class DeliveryChalanModule(QWidget):
    def __init__(self, user_data, parent=None):
        super().__init__(parent)
        self.setStyleSheet(APP_STYLE)
        self.user_data = user_data or {}
        self.setMinimumSize(1100, 650)  # tweak #1

        root = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        title = QLabel("🚚 Delivery Chalans")
        title.setStyleSheet("font-size: 20px; font-weight: 700; padding: 4px 2px;")
        header.addWidget(title)
        header.addStretch()

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search DC no / vehicle / person / branch / item… (type to filter)")
        self.search_box.textChanged.connect(self._apply_filter_to_table)
        header.addWidget(self.search_box)

        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet("color:#6b7280; padding:4px 2px;")
        header.addWidget(self.count_lbl)
        root.addLayout(header)

        # Toolbar
        tb = QToolBar()
        act_add = QAction(self.style().standardIcon(QStyle.SP_FileDialogNewFolder), "Add", self); act_add.triggered.connect(self._add_dc)
        act_refresh = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "Refresh", self); act_refresh.triggered.connect(self.load_list)
        tb.addAction(act_add); tb.addAction(act_refresh)
        root.addWidget(tb)

        # Table (updated headers/order; 'Branch' -> 'From'; stretch applied)
        self.tbl = QTableWidget(0, 10)
        self.tbl.setHorizontalHeaderLabels([
            "DC No", "Phys DC#", "Date", "Mode", "From", "To",
            "Vehicle", "Person", "Fare", "Total Qty"
        ])

        header = self.tbl.horizontalHeader()

        # 1) Start by letting ALL columns stretch...
        header.setSectionResizeMode(QHeaderView.Stretch)

        # 2) ...then pin compact columns to content width (so they don't eat space)
        for idx in (0, 1, 2, 3, 8, 9):  # DC No, Phys DC#, Date, Mode, Fare, Total Qty
            header.setSectionResizeMode(idx, QHeaderView.ResizeToContents)

        # Optional niceties
        header.setMinimumSectionSize(80)                 # don't get too skinny
        header.setStretchLastSection(True)               # ensure full-width fill
        self.tbl.setWordWrap(False)                      # keep rows compact
        self.tbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSortingEnabled(True)
        self.tbl.itemDoubleClicked.connect(self._open_detail)

        # IMPORTANT: make sure the layout actually allows stretching
        # If 'root' is a QBoxLayout (QVBoxLayout/QHBoxLayout), this is perfect:
        root.addWidget(self.tbl, 1)

        # If 'root' is a QGridLayout instead, use:
        # root.addWidget(self.tbl, 0, 0, 1, 1)
        # root.setRowStretch(0, 1)


        # initial load
        QTimer.singleShot(0, self.load_list)

    # --------- FASTNESS load pipeline ---------
    def load_list(self):
        # 1) cache-first (non-blocking)
        snap = _load_cache_json("delivery_chalans_snapshot.json")
        if snap.get("rows"):
            self._paint_rows(snap["rows"])

        # 2) show progress and refresh in background
        self._progress = QProgressDialog("Loading delivery chalans…", None, 0, 0, self)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setAutoClose(True)
        self._progress.show()

        was_sorting = self.tbl.isSortingEnabled()
        self.tbl.setSortingEnabled(False)

        self._loader = _DCsLoader()
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        self._loader.start()

        self._was_sorting = was_sorting

    def _on_loaded(self, rows):
        try:
            self._paint_rows(rows)
            _save_cache_json("delivery_chalans_snapshot.json", {"rows": rows})
        finally:
            try: self._progress.close()
            except Exception: pass
            self.tbl.setSortingEnabled(self._was_sorting)

    def _on_failed(self, msg):
        try: self._progress.close()
        except Exception: pass
        if not self.tbl.rowCount():
            QMessageBox.warning(self, "Load failed", msg)

    # --------- Painter + filter ---------
    def _paint_rows(self, rows):
        self.tbl.setRowCount(0)

        for d in rows:
            items = d.get("items") or []
            total_qty = sum(float(it.get("qty", 0) or 0) for it in items)

            # fare + payer
            fare = float(d.get("delivery_fare", 0.0) or 0.0)
            payer = str(d.get("delivery_fare_payer","") or "")
            fare_disp = f"{fare:,.2f}" if fare else "0.00"
            # Show who pays in compact form; header already clarifies (Sender, Receiver)
            payer_short = "Sender" if payer == "Sender Will Pay" else ("Receiver" if payer else "-")
            fare_cell_text = f"{fare_disp} ({payer_short})"

            mode = str(d.get("mode","") or "")
            to_branch = str(d.get("transfer_to_branch","") or "") if mode == "Inventory Transfer" else str(d.get("delivery_location", "") or "-")
            from_branch = str(d.get("branch","") or "")
            phys_dc_no = str(d.get("physical_dc_no", 0) or 0)

            row = self.tbl.rowCount()
            self.tbl.insertRow(row)

            cells = [
                str(d.get("dc_no","")),      # DC No
                phys_dc_no if str(phys_dc_no) != "0" else "-", # Phys DC#
                str(d.get("date","")),       # Date
                mode,                        # Mode
                from_branch,                 # From
                to_branch,                   # To
                str(d.get("vehicle_no","")), # Vehicle
                str(d.get("vehicle_person","")), # Person
                fare_cell_text,              # Fare (Sender, Receiver)
                f"{total_qty:g}",            # Total Qty
            ]

            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                # Stash doc id on the "DC No" column (index 0)
                if c == 0:
                    it.setData(Qt.UserRole, d.get("_doc_id"))
                self.tbl.setItem(row, c, it)

        self._apply_filter_to_table()



    def _apply_filter_to_table(self):
        term = (self.search_box.text() or "").lower()
        for r in range(self.tbl.rowCount()):
            row_text = " ".join(
                (self.tbl.item(r, c).text() if self.tbl.item(r, c) else "")
                for c in range(self.tbl.columnCount())
            ).lower()
            self.tbl.setRowHidden(r, term not in row_text)
        self._update_count_label()

    def _update_count_label(self):
        visible = sum(not self.tbl.isRowHidden(r) for r in range(self.tbl.rowCount()))
        self.count_lbl.setText(f"Total: {visible} DCs")

    # --------- Actions ---------
    def _add_dc(self):
        dlg = DeliveryChalanForm(self.user_data, self)
        if dlg.exec_():
            self.load_list()

    def _open_detail(self, _item):
        r = self.tbl.currentRow()
        if r < 0:
            return

        # We now stash _doc_id on column 0 ("DC No")
        it = self.tbl.item(r, 0)
        doc_id = it.data(Qt.UserRole) if it else None
        if not doc_id:
            QMessageBox.warning(self, "Missing", "This row has no stored document id.")
            return

        try:
            snap = db.collection("delivery_chalans").document(doc_id).get()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to fetch Delivery Chalan:\n{e}")
            return

        if not getattr(snap, "exists", False):
            QMessageBox.warning(self, "Missing", "This delivery chalan was removed.")
            self.load_list()
            return

        d = snap.to_dict() or {}
        d.setdefault("_doc_id", doc_id)
        DeliveryChalanDetailDialog(d, self).exec_()

