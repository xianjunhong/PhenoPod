"""豆荚拍照、实例分割、形态测量与结果保存。"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

from common.camera_base import CameraBase
from common.data_manager import DataManager
from common.model_manager import ModelManager
from common.pod_measurement import PodMeasurementEngine


class ModelLoadThread(QThread):
    load_finished = pyqtSignal(bool, str)

    def __init__(self, model_manager, model_name):
        super().__init__()
        self.model_manager = model_manager
        self.model_name = model_name

    def run(self):
        success, message, model = self.model_manager.load_model(self.model_name)
        if success and getattr(model, "task", None) != "segment":
            success = False
            message = "模型不是实例分割模型，无法执行豆荚轮廓测量"
            self.model_manager.current_model = None
        self.load_finished.emit(success, message)


class PodAnalysisThread(QThread):
    analysis_finished = pyqtSignal(object)
    analysis_failed = pyqtSignal(str)

    def __init__(self, model, image, engine_config):
        super().__init__()
        self.model = model
        self.image = image.copy()
        self.engine_config = dict(engine_config)

    def run(self):
        try:
            engine = PodMeasurementEngine(self.model, **self.engine_config)
            self.analysis_finished.emit(engine.analyze(self.image))
        except Exception as exc:
            import traceback

            traceback.print_exc()
            self.analysis_failed.emit(str(exc))


def _imwrite_unicode(path: str, image: np.ndarray) -> bool:
    suffix = Path(path).suffix or ".jpg"
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        return False
    encoded.tofile(path)
    return True


class InspectionHandler:
    """连接设备、UI 与豆荚测量算法。"""

    def __init__(self, ui, config_manager, model_name):
        self.ui = ui
        self.config_manager = config_manager
        self.model_name = model_name
        self.camera = CameraBase(config_manager)
        self.model_manager = ModelManager(config_manager)
        self.data_manager = DataManager(config_manager)
        self.pod_config = config_manager.get_pod_measurement_config()

        self.last_frame = None
        self.processed_image = None
        self.summary = {}
        self.pod_rows = []
        self.model_ready = False
        self.showing_processed = False
        self.last_source_type = "camera"
        self.last_source_path = ""
        self.analysis_thread = None

        self.ui.home_page.slider_confidence.setValue(
            int(round(self.pod_config["confidence"] * 100))
        )
        self.ui.home_page.spin_pixel_to_cm.setValue(self.pod_config["pixel_to_cm"])
        self.ui.home_page.set_process_ready(False)
        self._connect_signals()
        self._load_model()

    def _connect_signals(self):
        home = self.ui.home_page
        home.btn_enum_cam.clicked.connect(self.enum_cameras)
        home.btn_open_cam.clicked.connect(self.toggle_camera)
        home.button_live_img.clicked.connect(self.start_preview)
        home.button_import_img.clicked.connect(self.import_image)
        home.button_process_img.clicked.connect(self.process_image)
        home.button_toggle_view.clicked.connect(self.toggle_result_view)
        home.button_save_info.clicked.connect(self.save_data)

    def _load_model(self):
        self.ui.home_page.set_model_ready(False, "算法模型正在加载…")
        self.model_load_thread = ModelLoadThread(self.model_manager, self.model_name)
        self.model_load_thread.load_finished.connect(self._on_model_loaded)
        self.model_load_thread.start()

    def _on_model_loaded(self, success, message):
        self.model_ready = bool(success)
        if success:
            self.ui.home_page.set_model_ready(True, "豆荚分割与形态测量模型已就绪")
            self._refresh_process_ready()
        else:
            self.ui.home_page.set_model_ready(False, f"模型加载失败：{message}")
            QMessageBox.warning(self.ui, "模型加载失败", message)

    def _refresh_process_ready(self):
        busy = self.analysis_thread is not None and self.analysis_thread.isRunning()
        self.ui.home_page.set_process_ready(
            self.model_ready and self.last_frame is not None and not busy
        )

    # ---------- 相机 ----------
    def enum_cameras(self):
        success, message, devices = self.camera.enum_devices()
        if not success:
            QMessageBox.warning(self.ui, "设备扫描失败", message)
            return
        self.ui.home_page.combo_devices_cam.clear()
        self.ui.home_page.combo_devices_cam.addItems(devices)
        if not devices:
            QMessageBox.information(self.ui, "设备扫描", "未发现可用相机")

    def toggle_camera(self):
        if self.camera.is_open:
            self.close_camera()
        else:
            self.open_camera()

    def open_camera(self):
        index = self.ui.home_page.combo_devices_cam.currentIndex()
        if index < 0:
            QMessageBox.warning(self.ui, "提示", "请先扫描并选择图像设备")
            return
        success, message = self.camera.open_device(index)
        if not success:
            QMessageBox.warning(self.ui, "打开设备失败", message)
            return
        self.ui.home_page.btn_open_cam.setText("关闭设备")
        self.ui.home_page.button_live_img.setEnabled(True)
        self.start_preview()

    def close_camera(self):
        self.camera.stop_grabbing()
        self.camera.close_device()
        self.ui.home_page.btn_open_cam.setText("打开设备")
        self.ui.home_page.button_live_img.setEnabled(False)

    def start_preview(self):
        if not self.camera.is_open:
            QMessageBox.warning(self.ui, "提示", "请先打开图像设备")
            return
        self.showing_processed = False
        try:
            if self.camera.cam_thread:
                self.camera.cam_thread.image_update.disconnect(self.update_camera_image)
        except (TypeError, RuntimeError):
            pass
        success, message = self.camera.start_grabbing()
        if not success:
            QMessageBox.warning(self.ui, "预览失败", message)
            return
        try:
            self.camera.cam_thread.image_update.disconnect(self.update_camera_image)
        except (TypeError, RuntimeError):
            pass
        self.camera.cam_thread.image_update.connect(self.update_camera_image)
        self.ui.home_page.button_live_img.setEnabled(False)
        self.ui.home_page.button_toggle_view.setEnabled(False)
        self.ui.home_page.button_toggle_view.setText("查看原图")

    def update_camera_image(self, image):
        if self.showing_processed:
            return
        self.last_frame = image.copy()
        self.last_source_type = "camera"
        self.last_source_path = ""
        self.display_image(self.last_frame)
        self._refresh_process_ready()

    # ---------- 本地图像与算法 ----------
    def import_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.ui,
            "选择豆荚图像",
            "",
            "图像文件 (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp)",
        )
        if not file_path:
            return
        image = cv2.imdecode(np.fromfile(file_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            QMessageBox.warning(self.ui, "读取失败", "无法读取所选图像")
            return
        if self.camera.cam_thread and self.camera.cam_thread.running:
            self.camera.stop_grabbing()
        self.ui.home_page.button_live_img.setEnabled(self.camera.is_open)
        self.last_frame = image
        self.last_source_type = "file"
        self.last_source_path = file_path
        self.processed_image = None
        self.summary = {}
        self.pod_rows = []
        self.showing_processed = False
        self.ui.home_page.clear_result_display()
        self.ui.home_page.button_toggle_view.setEnabled(False)
        self.ui.home_page.button_save_info.setEnabled(False)
        if not self.ui.home_page.input_sample_code.text().strip():
            self.ui.home_page.input_sample_code.setText(Path(file_path).stem)
        self.display_image(image)
        self._refresh_process_ready()

    def process_image(self):
        if self.last_frame is None:
            QMessageBox.warning(self.ui, "提示", "请先打开设备拍照或导入一张图像")
            return
        if not self.model_ready or self.model_manager.current_model is None:
            QMessageBox.warning(self.ui, "提示", "豆荚测量模型尚未就绪")
            return
        if self.analysis_thread is not None and self.analysis_thread.isRunning():
            return

        if self.camera.cam_thread and self.camera.cam_thread.running:
            try:
                self.camera.cam_thread.image_update.disconnect(self.update_camera_image)
            except (TypeError, RuntimeError):
                pass
            self.camera.stop_grabbing()
            self.last_source_type = "camera"
            self.last_source_path = ""

        image = self.last_frame.copy()
        engine_config = {
            "pixel_to_cm": self.ui.home_page.spin_pixel_to_cm.value(),
            "imgsz": self.pod_config["imgsz"],
            "confidence": self.ui.home_page.slider_confidence.value() / 100.0,
            "iou": self.pod_config["iou"],
            "class_id": self.pod_config["class_id"],
            "refine_boundary": self.pod_config["refine_boundary"],
            "refine_margin_ratio": self.pod_config["refine_margin_ratio"],
            "minimum_color_separation": self.pod_config[
                "minimum_color_separation"
            ],
            "minimum_raw_refined_iou": self.pod_config[
                "minimum_raw_refined_iou"
            ],
            "minimum_edge_score_gain": self.pod_config[
                "minimum_edge_score_gain"
            ],
            "minimum_area_ratio": self.pod_config["minimum_area_ratio"],
            "maximum_area_ratio": self.pod_config["maximum_area_ratio"],
        }
        self.ui.home_page.set_busy(True)
        self.ui.home_page.button_save_info.setEnabled(False)
        QApplication.processEvents()

        self.analysis_thread = PodAnalysisThread(
            self.model_manager.current_model, image, engine_config
        )
        self.analysis_thread.analysis_finished.connect(self._on_analysis_finished)
        self.analysis_thread.analysis_failed.connect(self._on_analysis_failed)
        self.analysis_thread.finished.connect(self._on_analysis_thread_finished)
        self.analysis_thread.start()

    def _on_analysis_finished(self, payload):
        self.processed_image = payload["annotated_image"]
        self.summary = payload["summary"]
        self.pod_rows = payload["pods"]
        self.showing_processed = True
        self.display_image(self.processed_image)
        self.ui.home_page.update_result_display(self.summary, self.pod_rows)
        self.ui.home_page.button_toggle_view.setEnabled(True)
        self.ui.home_page.button_toggle_view.setText("查看原图")
        self.ui.home_page.button_save_info.setEnabled(True)
        self.ui.home_page.button_live_img.setEnabled(self.camera.is_open)
        if not self.pod_rows:
            QMessageBox.information(
                self.ui,
                "测量完成",
                "图像处理完成，但没有检测到可测量的豆荚。可降低置信度后重试。",
            )

    def _on_analysis_failed(self, error_message):
        self.ui.home_page.button_live_img.setEnabled(self.camera.is_open)
        QMessageBox.warning(self.ui, "算法处理失败", error_message)

    def _on_analysis_thread_finished(self):
        self.ui.home_page.set_busy(False)
        self._refresh_process_ready()

    def toggle_result_view(self):
        if self.processed_image is None or self.last_frame is None:
            return
        if self.showing_processed:
            self.display_image(self.last_frame)
            self.showing_processed = False
            self.ui.home_page.button_toggle_view.setText("查看测量图")
        else:
            self.display_image(self.processed_image)
            self.showing_processed = True
            self.ui.home_page.button_toggle_view.setText("查看原图")

    # ---------- 保存 ----------
    def save_data(self):
        if self.processed_image is None or self.last_frame is None or not self.summary:
            QMessageBox.warning(self.ui, "提示", "请先完成一次豆荚测量")
            return
        sample_code = self.ui.home_page.input_sample_code.text().strip()
        if not sample_code:
            sample_code = f"POD-{uuid.uuid4().hex[:8].upper()}"
            self.ui.home_page.input_sample_code.setText(sample_code)

        record_id = uuid.uuid4().hex[:12]
        record = self.data_manager.create_pod_measurement_record(
            record_id=record_id,
            sample_code=sample_code,
            summary=self.summary,
            pod_measurements=self.pod_rows,
            source_type=self.last_source_type,
            source_path=self.last_source_path,
            model_name=self.model_name,
        )
        if not _imwrite_unicode(record["image_path"], self.last_frame):
            QMessageBox.warning(self.ui, "保存失败", "无法保存原始图像")
            return
        if not _imwrite_unicode(record["processed_image_path"], self.processed_image):
            QMessageBox.warning(self.ui, "保存失败", "无法保存测量结果图")
            return

        self.data_manager.save_record(record)
        if hasattr(self.ui, "data_page"):
            self.ui.data_page.add_table_row(record, row_index=0)
        self.ui.home_page.button_save_info.setEnabled(False)
        QMessageBox.information(self.ui, "保存成功", f"样本 {sample_code} 的测量结果已保存")

    def display_image(self, image):
        if image is None:
            return
        widget = self.ui.home_page.widget_display
        pixmap = self.camera.image_to_pixmap(image, widget.width(), widget.height())
        if pixmap:
            widget.setPixmap(pixmap)

    def close_device(self):
        self.camera.stop_grabbing()
        self.camera.close_device()
