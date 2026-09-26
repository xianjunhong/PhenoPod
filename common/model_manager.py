"""Load the fixed single-class pod instance-segmentation model."""
import os

import numpy as np

from common.paths import resource_path, writable_path

# Keep Ultralytics settings/cache files inside the project. This avoids
# permission errors on Windows accounts with a read-only roaming profile.
os.environ.setdefault(
    "YOLO_CONFIG_DIR", writable_path(os.path.join("data", "ultralytics"))
)
os.makedirs(os.environ["YOLO_CONFIG_DIR"], exist_ok=True)

from ultralytics import YOLO


class ModelManager:
    """Own the one YOLO segmentation model used by this demonstration."""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.models_folder = config_manager.get(
            "Paths", "models_folder", fallback="models"
        )
        self.current_model = None
        self.current_model_name = None
        self.current_model_type = None

    def load_model(self, model_file):
        """Load and warm up the configured pod model.

        Returns ``(success, message, model)`` to match the existing handler
        contract.
        """
        model_path = resource_path(os.path.join(self.models_folder, model_file))
        if not os.path.isfile(model_path):
            return False, f"豆荚分割模型不存在: {model_path}", None

        try:
            model = YOLO(model_path)
            if getattr(model, "task", None) != "segment":
                return False, "配置的模型不是实例分割模型", None
            dummy_image = np.zeros((640, 640, 3), dtype=np.uint8)
            model.predict(dummy_image, verbose=False)
            self.current_model = model
            self.current_model_name = model_file
            self.current_model_type = "seg"
            return True, "豆荚实例分割模型加载成功", model
        except Exception as exc:
            return False, f"豆荚分割模型加载失败: {exc}", None

    def get_current_model_info(self):
        return {
            "name": self.current_model_name,
            "type": self.current_model_type,
            "loaded": self.current_model is not None,
        }
