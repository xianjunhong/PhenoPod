"""豆荚测量历史记录、结果图查看与表格导出。"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PrimaryPushButton


class InspectionDataPage(QWidget):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        self.btn_export = PrimaryPushButton("导出 Excel / CSV")
        self.btn_refresh = QPushButton("刷新")
        self.btn_clear_all = QPushButton("清空所有记录")
        self.btn_clear_all.setStyleSheet("background: #cf222e; color: white;")
        buttons.addWidget(self.btn_export)
        buttons.addWidget(self.btn_refresh)
        buttons.addStretch()
        buttons.addWidget(self.btn_clear_all)
        layout.addLayout(buttons)

        self.table_widget = QTableWidget(0, 10)
        self.table_widget.setHorizontalHeaderLabels(
            [
                "ID",
                "时间",
                "样本编号",
                "豆荚数",
                "平均长度(cm)",
                "平均宽度(cm)",
                "平均外弧(cm)",
                "平均内弧(cm)",
                "平均曲率",
                "操作",
            ]
        )
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_widget.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_widget.verticalHeader().setDefaultSectionSize(44)
        widths = [105, 145, 125, 62, 105, 105, 105, 105, 82, 185]
        for column, width in enumerate(widths):
            self.table_widget.setColumnWidth(column, width)
        self.table_widget.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table_widget)

        self.btn_export.clicked.connect(self.export_excel)
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_clear_all.clicked.connect(self.clear_all_data)

    def load_data(self):
        self.table_widget.setRowCount(0)
        for record in self.data_manager.load_records():
            self.add_table_row(record)

    def add_table_row(self, record, row_index=None):
        if row_index is None:
            row_index = self.table_widget.rowCount()
        self.table_widget.insertRow(row_index)
        values = [
            record.get("id", ""),
            record.get("timestamp", ""),
            record.get("sample_code", ""),
            record.get("count", 0),
            f"{record.get('avg_length', 0):.2f}",
            f"{record.get('avg_width', 0):.2f}",
            f"{record.get('avg_outer_side_length', 0):.2f}",
            f"{record.get('avg_inner_side_length', 0):.2f}",
            f"{record.get('avg_curvature', 0):.3f}",
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignCenter)
            self.table_widget.setItem(row_index, column, item)

        btn_view = PrimaryPushButton("查看结果图")
        btn_view.setFixedSize(90, 32)
        btn_view.clicked.connect(lambda: self.view_image(record))
        btn_delete = QPushButton("删除")
        btn_delete.setFixedSize(62, 32)
        btn_delete.setStyleSheet("background: #cf222e; color: white; border-radius: 4px;")
        btn_delete.clicked.connect(lambda: self.delete_record(record))
        cell = QWidget()
        row_layout = QHBoxLayout(cell)
        row_layout.setContentsMargins(4, 4, 4, 4)
        row_layout.addWidget(btn_view)
        row_layout.addWidget(btn_delete)
        self.table_widget.setCellWidget(row_index, 9, cell)

    def view_image(self, record):
        image_path = record.get("processed_image_path", "")
        if not os.path.exists(image_path):
            QMessageBox.warning(self, "文件不存在", image_path or "记录中没有结果图路径")
            return
        try:
            os.startfile(image_path)
        except Exception as exc:
            QMessageBox.warning(self, "打开失败", str(exc))

    def delete_record(self, record):
        record_id = record.get("id", "")
        reply = QMessageBox.question(
            self,
            "删除确认",
            f"确定删除记录 {record_id} 及其原图、结果图吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        success, message = self.data_manager.delete_record(record_id)
        if not success:
            QMessageBox.warning(self, "删除失败", message)
            return
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 0)
            if item and item.text() == str(record_id):
                self.table_widget.removeRow(row)
                break

    def export_excel(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出豆荚测量数据",
            "豆荚测量数据.xlsx",
            "Excel 文件 (*.xlsx);;CSV 文件 (*.csv)",
        )
        if not file_path:
            return
        success, message = self.data_manager.export_to_excel(file_path)
        if success:
            QMessageBox.information(self, "导出完成", message)
        else:
            QMessageBox.warning(self, "导出失败", message)

    def clear_all_data(self):
        reply = QMessageBox.question(
            self,
            "清空确认",
            "确定清空所有豆荚测量记录及其图像文件吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        success, message = self.data_manager.delete_all_records()
        if success:
            self.table_widget.setRowCount(0)
            QMessageBox.information(self, "已清空", message)
        else:
            QMessageBox.warning(self, "清空失败", message)
