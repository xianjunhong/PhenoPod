"""
设置模块 - 业务逻辑处理器
"""
import numpy as np
from PyQt5.QtWidgets import QMessageBox

from common.camera_base import CameraBase, align_roi_params


class SettingsHandler:
    """设置处理器"""
    
    def __init__(self, ui, config_manager):
        self.ui = ui
        self.config_manager = config_manager
        
        # 初始化相机
        self.camera = CameraBase(config_manager)
        
        # 加载配置
        self._load_config_to_ui()
        
        # 连接信号
        self._connect_signals()
    
    def _load_config_to_ui(self):
        """加载配置到UI"""
        # 相机配置
        camera_config = self.config_manager.get_camera_config()
        self.ui.input_exposure_time.setText(str(camera_config['exposure_time']))
        self.ui.input_gain.setText(str(camera_config['gain']))
        self.ui.input_frame_rate.setText(str(camera_config['frame_rate']))
        self.ui.input_cm_per_pixel.setText(str(camera_config['cm_per_pixel']))
        
        # ROI配置
        roi_config = self.config_manager.get_roi_config()
        if self.camera.is_open:
            preview_resolution = (self.camera.roi_width, self.camera.roi_height)
        else:
            preview_resolution = (
                camera_config['resolution_width'], camera_config['resolution_height']
            )
        self.ui.roi_selector.set_camera_resolution(*preview_resolution)
        self.ui.roi_selector.set_roi(
            roi_config['offset_x'], roi_config['offset_y'],
            roi_config['width'], roi_config['height']
        )
        self.ui.update_roi_display(
            roi_config['offset_x'],
            roi_config['offset_y'],
            roi_config['width'],
            roi_config['height']
        )
        self.ui.check_reverse_x.setChecked(roi_config['reverse_x'])
        self.ui.check_reverse_y.setChecked(roi_config['reverse_y'])
        
        # 豆荚算法配置
        pod_config = self.config_manager.get_pod_measurement_config()
        self.ui.input_pod_model.setText(str(pod_config['model_file']))
        self.ui.input_pod_confidence.setText(str(pod_config['confidence']))
        self.ui.input_pod_iou.setText(str(pod_config['iou']))
        self.ui.input_pod_imgsz.setText(str(pod_config['imgsz']))
        self.ui.input_pod_class_id.setText(str(pod_config['class_id']))
        self.ui.input_pod_pixel_to_cm.setText(str(pod_config['pixel_to_cm']))
        
        # 路径配置
        paths_config = self.config_manager.get_paths_config()
        self.ui.input_models_folder.setText(paths_config['models_folder'])
        self.ui.input_images_folder.setText(paths_config['images_folder'])
        self.ui.input_processed_folder.setText(paths_config['processed_folder'])
        self.ui.input_data_file.setText(paths_config['data_file'])
    
    def _connect_signals(self):
        """连接UI信号"""
        # 相机控制
        self.ui.btn_enum_camera.clicked.connect(self.enum_cameras)
        self.ui.btn_open_camera.clicked.connect(self.toggle_camera)
        
        # ROI控制
        self.ui.btn_apply_roi.clicked.connect(self.apply_roi)
        self.ui.roi_selector.roi_selected.connect(self.on_roi_selected)
        
        # 保存设置
        self.ui.btn_save_settings.clicked.connect(self.save_settings)
        self.ui.btn_reset_settings.clicked.connect(self.reset_settings)
    
    # ========== 相机控制 ==========
    def enum_cameras(self):
        """枚举相机"""
        success, message, device_list = self.camera.enum_devices()
        if success:
            self.ui.combo_camera.clear()
            self.ui.combo_camera.addItems(device_list)
        else:
            QMessageBox.warning(self.ui, "错误", message)
    
    def toggle_camera(self):
        """切换相机状态"""
        if self.camera.is_open:
            self.close_camera()
        else:
            self.open_camera()
    
    def open_camera(self):
        """打开相机"""
        device_index = self.ui.combo_camera.currentIndex()
        if device_index < 0:
            QMessageBox.warning(self.ui, "错误", "请先扫描并选择相机")
            return
        
        # 全画幅只用于本次框选预览，不写入用户配置。
        success, message = self.camera.open_device(device_index, full_frame=True)
        if success:
            # 坐标转换必须与本次预览实际使用的尺寸一致。
            self.ui.roi_selector.set_camera_resolution(
                self.camera.roi_width, self.camera.roi_height
            )
            self.ui.roi_selector.set_roi(
                int(self.ui.label_roi_x.text()), int(self.ui.label_roi_y.text()),
                int(self.ui.label_roi_width.text()), int(self.ui.label_roi_height.text())
            )
            
            self.ui.btn_open_camera.setText("关闭相机")
            # 打开相机后自动开始预览
            self.start_roi_preview()
        else:
            QMessageBox.warning(self.ui, "错误", f"打开相机失败: {message}")
    
    def close_camera(self):
        """关闭相机"""
        # 先断开信号连接
        if self.camera.cam_thread:
            try:
                self.camera.cam_thread.image_update.disconnect()
            except:
                pass
        
        self.camera.stop_grabbing()
        self.camera.close_device()
        
        self.ui.btn_open_camera.setText("打开相机")
        self.ui.btn_apply_roi.setEnabled(False)
        
        # 显示黑屏
        black_image = np.zeros((480, 640, 3), dtype=np.uint8)
        self.display_image(black_image)
    
    def start_roi_preview(self):
        """开始ROI预览"""
        if not self.camera.is_open:
            QMessageBox.warning(self.ui, "错误", "请先打开相机")
            return
        
        success, message = self.camera.start_grabbing()
        if success:
            # 先断开旧的信号连接（如果有）
            try:
                self.camera.cam_thread.image_update.disconnect(self.update_roi_preview)
            except:
                pass
            
            # 连接图像更新信号
            self.camera.cam_thread.image_update.connect(self.update_roi_preview)
            self.ui.btn_apply_roi.setEnabled(True)
            print("✅ ROI预览已启动")
        else:
            QMessageBox.warning(self.ui, "错误", message)
    
    def update_roi_preview(self, image):
        """更新ROI预览"""
        # 将图像转换为QPixmap并显示
        pixmap = self.camera.image_to_pixmap(
            image, 
            self.ui.roi_selector.width(), 
            self.ui.roi_selector.height()
        )
        if pixmap:
            self.ui.roi_selector.set_image(pixmap)
    
    # ========== ROI控制 ==========
    def on_roi_selected(self, x, y, w, h):
        """ROI被选中"""
        print(f"ROI选中: x={x}, y={y}, w={w}, h={h}")
        self.ui.update_roi_display(x, y, w, h)
    
    def apply_roi(self):
        """应用ROI"""
        roi = self.ui.roi_selector.get_roi()
        if roi:
            x, y, w, h = roi
            self.ui.update_roi_display(x, y, w, h)
            QMessageBox.information(self.ui, "提示", "选区已确认，请点击“保存设置”。测量页重新打开相机时应用保存的ROI。")
        else:
            QMessageBox.warning(self.ui, "提示", "请先框选ROI区域")
    
    # ========== 设置保存 ==========
    def save_settings(self):
        """保存设置"""
        try:
            # 先验证所有输入，避免后续字段无效时只保存了部分设置。
            camera_settings = dict(
                exposure_time=float(self.ui.input_exposure_time.text()),
                gain=float(self.ui.input_gain.text()),
                frame_rate=float(self.ui.input_frame_rate.text()),
                cm_per_pixel=float(self.ui.input_cm_per_pixel.text())
            )

            confidence = float(self.ui.input_pod_confidence.text())
            iou = float(self.ui.input_pod_iou.text())
            pixel_to_cm = float(self.ui.input_pod_pixel_to_cm.text())
            imgsz = int(self.ui.input_pod_imgsz.text())
            class_id = int(self.ui.input_pod_class_id.text())
            if not 0 < confidence <= 1 or not 0 < iou <= 1:
                raise ValueError("置信度和 IoU 必须在 (0, 1] 范围内")
            if pixel_to_cm <= 0:
                raise ValueError("像素标定值必须为正数")
            if imgsz < 32:
                raise ValueError("推理尺寸不能小于 32")
            
            # 获取ROI参数
            offset_x = int(self.ui.label_roi_x.text())
            offset_y = int(self.ui.label_roi_y.text())
            width = int(self.ui.label_roi_width.text())
            height = int(self.ui.label_roi_height.text())
            
            # 对齐ROI参数（海康相机要求4字节对齐）
            camera_resolution = self.ui.roi_selector.camera_resolution
            aligned_offset_x, aligned_offset_y, aligned_width, aligned_height = align_roi_params(
                offset_x, offset_y, width, height,
                camera_resolution[0], camera_resolution[1],
                alignment=4
            )
            
            # 如果参数被调整，提示用户
            if (aligned_offset_x != offset_x or aligned_offset_y != offset_y or 
                aligned_width != width or aligned_height != height):
                QMessageBox.information(
                    self.ui, "参数对齐", 
                    f"ROI参数已自动对齐以满足相机要求：\n\n"
                    f"原始: offset=({offset_x}, {offset_y}), size=({width}×{height})\n"
                    f"对齐后: offset=({aligned_offset_x}, {aligned_offset_y}), size=({aligned_width}×{aligned_height})\n\n"
                    f"海康相机要求ROI参数必须是4的倍数。"
                )
                # 更新UI显示
                self.ui.update_roi_display(aligned_offset_x, aligned_offset_y, aligned_width, aligned_height)
            
            # 仅在用户明确保存时写入配置。
            self.config_manager.set_camera_config(**camera_settings)
            self.config_manager.set_roi_config(
                offset_x=aligned_offset_x,
                offset_y=aligned_offset_y,
                width=aligned_width,
                height=aligned_height,
                reverse_x=self.ui.check_reverse_x.isChecked(),
                reverse_y=self.ui.check_reverse_y.isChecked()
            )
            
            # 保存豆荚分割与形态测量配置
            self.config_manager.set_pod_measurement_config(
                model_file=self.ui.input_pod_model.text().strip(),
                confidence=confidence,
                iou=iou,
                imgsz=imgsz,
                class_id=class_id,
                pixel_to_cm=pixel_to_cm,
            )
            
            # 路径配置需要手动修改配置文件
            # 这里只验证格式
            
            self.ui.roi_selector.set_roi(
                aligned_offset_x, aligned_offset_y, aligned_width, aligned_height
            )
            QMessageBox.information(
                self.ui, "成功",
                "设置已保存！测量页重新打开相机时应用ROI。\n设置页保持全画幅预览，绿色框表示保存的选区。"
            )
            
        except ValueError as e:
            QMessageBox.warning(self.ui, "错误", f"参数格式错误：{str(e)}")
        except Exception as e:
            QMessageBox.warning(self.ui, "错误", f"保存失败：{str(e)}")
    
    def reset_settings(self):
        """重置为默认设置"""
        reply = QMessageBox.question(
            self.ui, "确认",
            "确定要恢复默认设置吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 创建默认配置
            self.config_manager._create_default_config()
            self.config_manager.save()
            
            # 重新加载到UI
            self._load_config_to_ui()
            
            QMessageBox.information(self.ui, "成功", "已恢复默认设置")
    
    # ========== 显示工具 ==========
    def display_image(self, image):
        """显示图像"""
        pixmap = self.camera.image_to_pixmap(
            image,
            self.ui.roi_selector.width(),
            self.ui.roi_selector.height()
        )
        if pixmap:
            self.ui.roi_selector.set_image(pixmap)
    
    # ========== 清理 ==========
    def cleanup(self):
        """清理资源（离开设置页面时调用）"""
        print("🧹 清理设置页面资源...")
        
        # 断开所有信号连接
        if self.camera.cam_thread:
            try:
                self.camera.cam_thread.image_update.disconnect()
                print("✅ 已断开相机信号")
            except:
                pass
        
        # 关闭相机
        self.camera.stop_grabbing()
        self.camera.close_device()
        
        # 重置UI状态
        self.ui.btn_open_camera.setText("打开相机")
        self.ui.btn_apply_roi.setEnabled(False)
        
        # 清理ROI选择器状态
        self.ui.roi_selector.clear_roi()
        self.ui.roi_selector.original_pixmap = None
        self.ui.roi_selector.image_rect = None
        self.ui.roi_selector.clear()
        self.ui.roi_selector.setText("请打开相机开始预览")
        # 页面会被复用；再次进入时显示已保存的设置，丢弃未保存的草稿。
        self._load_config_to_ui()
        
        print("✅ 设置页面资源清理完成")
    
    def close_device(self):
        """关闭设备"""
        self.cleanup()
