"""豆荚智能测量演示主页。"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PrimaryPushButton


class InspectionHomePage(QWidget):
    """相机/本地图像输入、豆荚测量结果和算法可视化。"""

    def __init__(self, confidence=0.25, pixel_to_cm=0.007433):
        super().__init__()
        self.initial_confidence = float(confidence)
        self.initial_pixel_to_cm = float(pixel_to_cm)
        self.setup_ui()

    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(14)

        left_layout = QVBoxLayout()
        title = QLabel("豆荚实例分割与形态测量")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        title.setStyleSheet("color: #146C43; margin: 2px 0 6px 0;")
        left_layout.addWidget(title)

        self.widget_display = QLabel("可打开设备实时预览，也可以导入一张豆荚照片")
        self.widget_display.setMinimumSize(700, 525)
        self.widget_display.setStyleSheet(
            "border: 2px solid #b8c8bf; border-radius: 8px; "
            "background-color: #101412; color: #d7e3dc;"
        )
        self.widget_display.setAlignment(Qt.AlignCenter)
        self.widget_display.setScaledContents(False)

        self.loading_progress = QProgressBar(self.widget_display)
        self.loading_progress.setFixedSize(400, 28)
        self.loading_progress.setRange(0, 0)
        self.loading_progress.setTextVisible(False)
        self.loading_progress.setStyleSheet(
            "QProgressBar {border: none; border-radius: 14px; "
            "background: rgba(220, 230, 224, 180);} "
            "QProgressBar::chunk {border-radius: 14px; background: #22A06B;}"
        )
        self.loading_progress.hide()
        original_resize = self.widget_display.resizeEvent

        def resize_display(event):
            original_resize(event)
            self._center_loading_progress()

        self.widget_display.resizeEvent = resize_display
        left_layout.addWidget(self.widget_display, 1)

        action_layout = QHBoxLayout()
        self.button_live_img = QPushButton("继续实时预览")
        self.button_live_img.setEnabled(False)
        self.button_import_img = QPushButton("导入图片")
        self.button_process_img = PrimaryPushButton("拍照并测量")
        self.button_process_img.setEnabled(False)
        self.button_toggle_view = QPushButton("查看原图")
        self.button_toggle_view.setEnabled(False)
        action_layout.addWidget(self.button_live_img)
        action_layout.addWidget(self.button_import_img)
        action_layout.addWidget(self.button_process_img)
        action_layout.addWidget(self.button_toggle_view)
        left_layout.addLayout(action_layout)

        legend = QLabel(
            "图例：半透明色=分割掩膜　紫=真实轮廓　黄=端点弦长　蓝=最大内切圆　"
            "橙=外弧　绿=最小旋转矩形"
        )
        legend.setWordWrap(True)
        legend.setStyleSheet(
            "background: #eef7f1; color: #315c43; padding: 7px; border-radius: 5px;"
        )
        left_layout.addWidget(legend)
        main_layout.addLayout(left_layout, 3)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(9)
        right_layout.addWidget(self._create_camera_group())
        right_layout.addWidget(self._create_algorithm_group())
        right_layout.addWidget(self._create_sample_group())
        right_layout.addWidget(self._create_result_group())
        right_layout.addWidget(self._create_detail_group(), 1)

        self.label_model_status = QLabel("算法模型正在加载…")
        self.label_model_status.setStyleSheet(
            "color: #9a6700; background: #fff8c5; padding: 6px; border-radius: 4px;"
        )
        right_layout.addWidget(self.label_model_status)

        self.button_save_info = PrimaryPushButton("保存本次测量")
        self.button_save_info.setMinimumHeight(40)
        self.button_save_info.setEnabled(False)
        right_layout.addWidget(self.button_save_info)
        main_layout.addLayout(right_layout, 2)

    def _create_camera_group(self):
        group = QGroupBox("图像设备")
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self.combo_devices_cam = QComboBox()
        self.btn_enum_cam = QPushButton("扫描设备")
        self.btn_open_cam = PrimaryPushButton("打开设备")
        row.addWidget(self.combo_devices_cam, 1)
        row.addWidget(self.btn_enum_cam)
        layout.addLayout(row)
        layout.addWidget(self.btn_open_cam)
        note = QLabel("打开设备后实时预览，点击“拍照并测量”冻结当前画面并运行算法。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #66736b; font-size: 12px;")
        layout.addWidget(note)
        return group

    def _create_algorithm_group(self):
        group = QGroupBox("算法参数")
        layout = QGridLayout(group)
        self.slider_confidence = QSlider(Qt.Horizontal)
        self.slider_confidence.setRange(5, 95)
        self.slider_confidence.setValue(int(round(self.initial_confidence * 100)))
        self.label_confidence = QLabel(f"{self.initial_confidence:.0%}")
        self.slider_confidence.valueChanged.connect(
            lambda value: self.label_confidence.setText(f"{value}%")
        )

        self.spin_pixel_to_cm = QDoubleSpinBox()
        self.spin_pixel_to_cm.setDecimals(6)
        self.spin_pixel_to_cm.setRange(0.000001, 1.0)
        self.spin_pixel_to_cm.setSingleStep(0.000001)
        self.spin_pixel_to_cm.setValue(self.initial_pixel_to_cm)
        self.spin_pixel_to_cm.setSuffix(" cm/px")

        layout.addWidget(QLabel("分割置信度:"), 0, 0)
        layout.addWidget(self.slider_confidence, 0, 1)
        layout.addWidget(self.label_confidence, 0, 2)
        layout.addWidget(QLabel("像素标定:"), 1, 0)
        layout.addWidget(self.spin_pixel_to_cm, 1, 1, 1, 2)
        return group

    def _create_sample_group(self):
        group = QGroupBox("样本信息")
        layout = QHBoxLayout(group)
        layout.addWidget(QLabel("样本编号:"))
        self.input_sample_code = QLineEdit()
        self.input_sample_code.setPlaceholderText("可选；留空将自动生成")
        layout.addWidget(self.input_sample_code, 1)
        return group

    def _create_result_group(self):
        group = QGroupBox("整图测量结果")
        layout = QGridLayout(group)
        self.label_count = QLabel("0")
        self.label_avg_length = QLabel("0.00 cm")
        self.label_avg_width = QLabel("0.00 cm")
        self.label_avg_outer = QLabel("0.00 cm")
        self.label_avg_inner = QLabel("0.00 cm")
        self.label_avg_curvature = QLabel("0.000")
        self.label_avg_rect = QLabel("0.00 × 0.00 cm")
        result_labels = [
            self.label_count,
            self.label_avg_length,
            self.label_avg_width,
            self.label_avg_outer,
            self.label_avg_inner,
            self.label_avg_curvature,
            self.label_avg_rect,
        ]
        for label in result_labels:
            label.setStyleSheet("font-weight: bold; color: #146C43;")

        fields = [
            ("豆荚数量:", self.label_count),
            ("平均长度:", self.label_avg_length),
            ("平均宽度:", self.label_avg_width),
            ("平均外弧长:", self.label_avg_outer),
            ("平均内弧长:", self.label_avg_inner),
            ("平均曲率:", self.label_avg_curvature),
            ("旋转矩形均值:", self.label_avg_rect),
        ]
        for row, (name, value) in enumerate(fields):
            layout.addWidget(QLabel(name), row, 0)
            layout.addWidget(value, row, 1)
        return group

    def _create_detail_group(self):
        group = QGroupBox("逐荚明细")
        layout = QVBoxLayout(group)
        self.table_details = QTableWidget(0, 8)
        self.table_details.setHorizontalHeaderLabels(
            ["#", "置信度", "长度", "宽度", "外弧", "内弧", "曲率", "矩形长×宽"]
        )
        self.table_details.setAlternatingRowColors(True)
        self.table_details.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_details.verticalHeader().setVisible(False)
        self.table_details.horizontalHeader().setStretchLastSection(True)
        widths = [34, 58, 62, 62, 62, 62, 54]
        for column, width in enumerate(widths):
            self.table_details.setColumnWidth(column, width)
        layout.addWidget(self.table_details)
        return group

    def _center_loading_progress(self):
        x = (self.widget_display.width() - self.loading_progress.width()) // 2
        y = (self.widget_display.height() - self.loading_progress.height()) // 2
        self.loading_progress.move(max(0, x), max(0, y))

    def set_busy(self, busy: bool):
        self._center_loading_progress()
        self.loading_progress.setVisible(busy)
        if busy:
            self.loading_progress.raise_()
        ready = self.button_process_img.property("ready") is True
        self.button_process_img.setEnabled(not busy and ready)
        self.button_import_img.setEnabled(not busy)

    def set_model_ready(self, ready: bool, message: str):
        self.label_model_status.setText(message)
        if ready:
            self.label_model_status.setStyleSheet(
                "color: #146C43; background: #dafbe1; padding: 6px; border-radius: 4px;"
            )
        else:
            self.label_model_status.setStyleSheet(
                "color: #cf222e; background: #ffebe9; padding: 6px; border-radius: 4px;"
            )

    def set_process_ready(self, ready: bool):
        self.button_process_img.setProperty("ready", bool(ready))
        self.button_process_img.setEnabled(bool(ready))

    def update_result_display(self, summary: dict, pods: list[dict]):
        self.label_count.setText(str(summary.get("count", 0)))
        self.label_avg_length.setText(f"{summary.get('avg_length', 0):.2f} cm")
        self.label_avg_width.setText(f"{summary.get('avg_width', 0):.2f} cm")
        self.label_avg_outer.setText(f"{summary.get('avg_outer_side_length', 0):.2f} cm")
        self.label_avg_inner.setText(f"{summary.get('avg_inner_side_length', 0):.2f} cm")
        self.label_avg_curvature.setText(f"{summary.get('avg_curvature', 0):.3f}")
        self.label_avg_rect.setText(
            f"{summary.get('avg_rect_length', 0):.2f} × {summary.get('avg_rect_width', 0):.2f} cm"
        )

        self.table_details.setRowCount(len(pods))
        for row, pod in enumerate(pods):
            values = [
                pod.get("pod_index", row + 1),
                f"{pod.get('confidence', 0):.2f}",
                f"{pod.get('length_cm', 0):.2f}",
                f"{pod.get('width_cm', 0):.2f}",
                f"{pod.get('outer_side_length_cm', 0):.2f}",
                f"{pod.get('inner_side_length_cm', 0):.2f}",
                f"{pod.get('curvature', 0):.3f}",
                f"{pod.get('rect_length_cm', 0):.2f}×{pod.get('rect_width_cm', 0):.2f}",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                self.table_details.setItem(row, column, item)

    def clear_result_display(self):
        self.update_result_display({}, [])
