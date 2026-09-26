"""ROI persistence regressions using real Qt widgets and a simulated camera SDK."""
import os
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import numpy as np
from PyQt5.QtWidgets import QApplication, QMessageBox

from common.camera_base import CameraBase
from common.config_manager import ConfigManager
from modules.settings.settings_handler import SettingsHandler
from modules.settings.settings_ui import SettingsUI


class CameraSDK:
    """Record SDK writes and enforce sensor bounds without touching hardware."""

    def __init__(self, width=4024, height=3036):
        self.values = dict(WidthMax=width, HeightMax=height, Width=width,
                           Height=height, OffsetX=0, OffsetY=0)
        self.closed = False
        self.destroyed = False
        self.open_error = 0
        self.width_error = 0

    def MV_CC_OpenDevice(self, *args):
        self.closed = False
        self.destroyed = False
        return self.open_error

    def MV_CC_CloseDevice(self):
        self.closed = True
        return 0

    def MV_CC_DestroyHandle(self):
        self.destroyed = True
        return 0

    def MV_CC_GetIntValue(self, name, result):
        result.nCurValue = self.values[name]
        return 0

    def MV_CC_SetIntValue(self, name, value):
        if name == "Width" and self.width_error:
            return self.width_error
        proposed = dict(self.values, **{name: value})
        if (value < 0 or proposed['OffsetX'] + proposed['Width'] > proposed['WidthMax']
                or proposed['OffsetY'] + proposed['Height'] > proposed['HeightMax']):
            return 1
        self.values[name] = value
        return 0

    def MV_CC_SetBoolValue(self, name, value):
        self.values[name] = value
        return 0

    def MV_CC_SetEnumValue(self, name, value):
        return 0

    def MV_CC_SetFloatValue(self, name, value):
        self.values[name] = value
        return 0


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def config(tmp_path):
    manager = ConfigManager(str(tmp_path / "config.ini"))
    manager.set_roi_config(400, 200, 1600, 1200)
    return manager


@pytest.fixture
def sdk():
    device = CameraSDK()
    with patch("common.camera_base.cam_tool.creat_camera", return_value=(device, None)):
        yield device


@pytest.fixture
def settings(app, config):
    ui = SettingsUI()
    handler = SettingsHandler(ui, config)
    ui.combo_camera.addItem("Test camera")
    handler.camera.deviceList = object()
    # Exercise device configuration but never start a hardware acquisition thread.
    handler.start_roi_preview = Mock()
    with patch("modules.settings.settings_handler.QMessageBox.information"), \
            patch("modules.settings.settings_handler.QMessageBox.warning") as warning:
        yield handler, warning
    handler.camera.close_device()
    ui.close()


def stored_roi(config):
    saved = config.get_roi_config()
    return tuple(saved[key] for key in ("offset_x", "offset_y", "width", "height"))


def assert_hardware_roi(sdk, roi):
    assert tuple(sdk.values[key] for key in ("OffsetX", "OffsetY", "Width", "Height")) == roi


def sdk_frame(sdk, sensor):
    """MV-CU120-10UC crops in sensor coordinates, then reverses the image."""
    nodes = sdk.values
    x, y, w, h = (nodes[key] for key in ("OffsetX", "OffsetY", "Width", "Height"))
    frame = sensor[y:y + h, x:x + w]
    if nodes["ReverseX"]:
        frame = frame[:, ::-1]
    if nodes["ReverseY"]:
        frame = frame[::-1]
    return frame


@pytest.mark.parametrize("reverse_x, reverse_y", [(False, False), (True, False), (False, True), (True, True)])
def test_measurement_frame_matches_selection_in_mirrored_full_preview(config, sdk, reverse_x, reverse_y):
    # Unique sensor pixels make any coordinate shift or double flip detectable.
    sensor = np.arange(4024 * 3036, dtype=np.int32).reshape(3036, 4024)
    config.set_roi_config(552, 228, 2812, 2732, reverse_x, reverse_y)
    camera = CameraBase(config)
    camera.deviceList = object()
    config_bytes = Path(config.config_path).read_bytes()
    assert camera.open_device(0, full_frame=True)[0]
    full_preview = sdk_frame(sdk, sensor)
    selected = full_preview[228:228 + 2732, 552:552 + 2812].copy()
    camera.close_device()
    assert camera.open_device(0)[0]
    np.testing.assert_array_equal(sdk_frame(sdk, sensor), selected)
    assert (camera.roi_offset_x, camera.roi_offset_y) == (552, 228)
    camera.close_device()
    assert Path(config.config_path).read_bytes() == config_bytes


def test_entering_settings_loads_saved_selection(settings, config):
    handler, _ = settings
    assert handler.ui.roi_selector.get_roi() == stored_roi(config)
    assert handler.ui.roi_selector.camera_resolution == (4024, 3036)


def test_preview_preserves_saved_config_and_selection(settings, config, sdk):
    handler, warning = settings
    original = config.get_roi_config()
    original_bytes = Path(config.config_path).read_bytes()
    with patch.object(config, "save", wraps=config.save) as save:
        for _ in range(2):
            handler.open_camera()
            assert handler.camera.is_open
            assert_hardware_roi(sdk, (0, 0, 4024, 3036))
            assert handler.ui.roi_selector.get_roi() == (400, 200, 1600, 1200)
            handler.cleanup()
        save.assert_not_called()
    assert config.get_roi_config() == original
    assert Path(config.config_path).read_bytes() == original_bytes
    warning.assert_not_called()


@pytest.mark.parametrize("initially_opened", [False, True])
def test_reused_measurement_camera_loads_new_settings(config, sdk, initially_opened):
    camera = CameraBase(config)
    camera.deviceList = object()
    if initially_opened:
        assert camera.open_device(0)[0]
        camera.close_device()
    config.set_roi_config(100, 200, 800, 600, False, False)
    config.set_camera_config(exposure_time=25000)
    assert camera.open_device(0)[0]
    assert_hardware_roi(sdk, (100, 200, 800, 600))
    assert sdk.values["ReverseX"] is False
    assert sdk.values["ExposureTime"] == 25000
    camera.close_device()


def test_saving_without_preview_keeps_configured_resolution(settings, config):
    handler, warning = settings
    config.set_roi_config(0, 0, 4024, 3036)
    handler._load_config_to_ui()
    handler.save_settings()
    assert stored_roi(config) == (0, 0, 4024, 3036)
    warning.assert_not_called()


def test_confirming_draft_does_not_save_and_leaving_restores_saved_selection(settings, config):
    handler, _ = settings
    original_bytes = Path(config.config_path).read_bytes()
    handler.ui.roi_selector.set_roi(100, 200, 800, 600)
    handler.on_roi_selected(100, 200, 800, 600)
    handler.apply_roi()
    assert handler.ui.label_roi_width.text() == "800"
    assert Path(config.config_path).read_bytes() == original_bytes
    handler.cleanup()
    assert handler.ui.roi_selector.get_roi() == (400, 200, 1600, 1200)
    assert handler.ui.label_roi_width.text() == "1600"
    assert Path(config.config_path).read_bytes() == original_bytes


def test_save_survives_preview_reopen_and_applies_in_measurement(settings, config, sdk):
    handler, warning = settings
    measurement = CameraBase(config)
    measurement.deviceList = object()
    handler.open_camera()
    handler.ui.roi_selector.set_roi(103, 205, 805, 605)
    handler.on_roi_selected(103, 205, 805, 605)
    handler.save_settings()
    expected = (100, 204, 804, 604)
    assert stored_roi(ConfigManager(config.config_path)) == expected
    assert handler.ui.roi_selector.get_roi() == expected
    handler.cleanup()
    handler.open_camera()
    assert_hardware_roi(sdk, (0, 0, 4024, 3036))
    assert handler.ui.roi_selector.get_roi() == expected
    handler.cleanup()
    assert measurement.open_device(0)[0]
    # 默认X/Y翻转均开启，设备接收传感器坐标，UI/配置继续保存预览坐标。
    assert_hardware_roi(sdk, (3120, 2228, 804, 604))
    measurement.close_device()
    warning.assert_not_called()


@pytest.mark.parametrize("answer", [QMessageBox.No, QMessageBox.Yes])
def test_restore_defaults_requires_confirmation(settings, config, sdk, answer):
    handler, _ = settings
    handler.open_camera()
    original_bytes = Path(config.config_path).read_bytes()
    with patch("modules.settings.settings_handler.QMessageBox.question", return_value=answer):
        handler.reset_settings()
    expected = (600, 112, 2852, 2804) if answer == QMessageBox.Yes else (400, 200, 1600, 1200)
    assert stored_roi(ConfigManager(config.config_path)) == expected
    assert handler.ui.roi_selector.get_roi() == expected
    assert_hardware_roi(sdk, (0, 0, 4024, 3036))
    if answer == QMessageBox.No:
        assert Path(config.config_path).read_bytes() == original_bytes


@pytest.mark.parametrize("failure", ["open", "roi", "resolution"])
def test_preview_failure_or_resolution_fallback_never_writes_config(settings, config, sdk, failure):
    handler, warning = settings
    if failure == "open":
        sdk.open_error = 1
    elif failure == "roi":
        sdk.width_error = 1
    else:
        sdk.MV_CC_GetIntValue = Mock(side_effect=RuntimeError("Resolution unavailable"))
    original_bytes = Path(config.config_path).read_bytes()
    handler.open_camera()
    assert Path(config.config_path).read_bytes() == original_bytes
    assert stored_roi(config) == (400, 200, 1600, 1200)
    if failure == "resolution":
        assert_hardware_roi(sdk, (0, 0, 4024, 3036))
        warning.assert_not_called()
    else:
        assert not handler.camera.is_open
        assert sdk.destroyed
        warning.assert_called_once()


def test_full_frame_uses_actual_sensor_size_without_saving(settings, config, sdk):
    handler, _ = settings
    sdk.values.update(WidthMax=4096, HeightMax=3072, Width=4096, Height=3072)
    original_bytes = Path(config.config_path).read_bytes()
    handler.open_camera()
    assert_hardware_roi(sdk, (0, 0, 4096, 3072))
    assert handler.ui.roi_selector.camera_resolution == (4096, 3072)
    handler.camera.close_device()
    assert handler.camera.open_device(0)[0]
    # 坐标映射采用设备真实全画幅尺寸，而不是配置中的4024x3036。
    assert_hardware_roi(sdk, (2096, 1672, 1600, 1200))
    assert Path(config.config_path).read_bytes() == original_bytes


def test_invalid_save_does_not_partially_write_roi(settings, config):
    handler, warning = settings
    original_bytes = Path(config.config_path).read_bytes()
    handler.ui.update_roi_display(100, 200, 800, 600)
    handler.ui.input_pod_confidence.setText("invalid")
    handler.save_settings()
    assert Path(config.config_path).read_bytes() == original_bytes
    assert stored_roi(config) == (400, 200, 1600, 1200)
    warning.assert_called_once()
