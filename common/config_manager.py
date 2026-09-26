"""
配置管理器
负责读取和保存 config.ini 配置文件
"""
import configparser
import os


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_path='config.ini'):
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.load()
    
    def load(self):
        """加载配置文件"""
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding='utf-8')
        else:
            # 创建默认配置
            self._create_default_config()
            self.save()
    
    def save(self):
        """保存配置文件"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)
    
    def _create_default_config(self):
        """创建默认配置"""
        # 相机配置
        self.config['Camera'] = {
            'resolution_width': '4024',
            'resolution_height': '3036',
            'exposure_time': '50000',
            'gain': '0',
            'frame_rate': '30.0',
            'cm_per_pixel': '0.007433'
        }
        
        # ROI 配置
        self.config['ROI'] = {
            'offset_x': '600',
            'offset_y': '112',
            'width': '2852',
            'height': '2804',
            'reverse_x': 'True',
            'reverse_y': 'True'
        }
        
        # 天平配置
        self.config['Balance'] = {
            'port': 'COM3',
            'baudrate': '9600',
            'timeout': '1.0'
        }
        
        # 检测配置
        self.config['Detection'] = {
            'default_confidence': '25.0',
            'default_area_filter': '5.0',
            'inference_confidence': '0.25'
        }

        # 豆荚实例分割与形态测量配置
        self.config['PodMeasurement'] = {
            'model_file': 'pod_seg.pt',
            'pixel_to_cm': '0.007433',
            'imgsz': '1024',
            'confidence': '0.25',
            'iou': '0.70',
            'class_id': '0'
        }
        
        # 路径配置
        self.config['Paths'] = {
            'models_folder': 'models',
            'images_folder': 'data/images',
            'processed_folder': 'data/processed',
            'data_file': 'data/records.json'
        }
    
    # ========== 相机配置 ==========
    def get_camera_config(self):
        """获取相机配置"""
        return {
            'resolution_width': self.config.getint('Camera', 'resolution_width'),
            'resolution_height': self.config.getint('Camera', 'resolution_height'),
            'exposure_time': self.config.getfloat('Camera', 'exposure_time'),
            'gain': self.config.getfloat('Camera', 'gain'),
            'frame_rate': self.config.getfloat('Camera', 'frame_rate'),
            'cm_per_pixel': self.config.getfloat('Camera', 'cm_per_pixel')
        }
    
    def set_camera_config(self, **kwargs):
        """设置相机配置"""
        for key, value in kwargs.items():
            if key in self.config['Camera']:
                self.config['Camera'][key] = str(value)
        self.save()
    
    # ========== ROI 配置 ==========
    def get_roi_config(self):
        """获取 ROI 配置"""
        return {
            'offset_x': self.config.getint('ROI', 'offset_x'),
            'offset_y': self.config.getint('ROI', 'offset_y'),
            'width': self.config.getint('ROI', 'width'),
            'height': self.config.getint('ROI', 'height'),
            'reverse_x': self.config.getboolean('ROI', 'reverse_x'),
            'reverse_y': self.config.getboolean('ROI', 'reverse_y')
        }
    
    def set_roi_config(self, offset_x, offset_y, width, height, reverse_x=None, reverse_y=None):
        """设置 ROI 配置"""
        self.config['ROI']['offset_x'] = str(offset_x)
        self.config['ROI']['offset_y'] = str(offset_y)
        self.config['ROI']['width'] = str(width)
        self.config['ROI']['height'] = str(height)
        if reverse_x is not None:
            self.config['ROI']['reverse_x'] = str(reverse_x)
        if reverse_y is not None:
            self.config['ROI']['reverse_y'] = str(reverse_y)
        self.save()
    
    # ========== 天平配置 ==========
    def get_balance_config(self):
        """获取天平配置"""
        return {
            'port': self.config.get('Balance', 'port'),
            'baudrate': self.config.getint('Balance', 'baudrate'),
            'timeout': self.config.getfloat('Balance', 'timeout')
        }
    
    def set_balance_config(self, port=None, baudrate=None, timeout=None):
        """设置天平配置"""
        if port:
            self.config['Balance']['port'] = port
        if baudrate:
            self.config['Balance']['baudrate'] = str(baudrate)
        if timeout:
            self.config['Balance']['timeout'] = str(timeout)
        self.save()
    
    # ========== 检测配置 ==========
    def get_detection_config(self):
        """获取检测配置"""
        return {
            'default_confidence': self.config.getfloat('Detection', 'default_confidence'),
            'default_area_filter': self.config.getfloat('Detection', 'default_area_filter'),
            'inference_confidence': self.config.getfloat('Detection', 'inference_confidence')
        }
    
    def set_detection_config(self, **kwargs):
        """设置检测配置"""
        for key, value in kwargs.items():
            if key in self.config['Detection']:
                self.config['Detection'][key] = str(value)
        self.save()

    # ========== 豆荚测量配置 ==========
    def get_pod_measurement_config(self):
        """获取单张图片豆荚分割与形态测量参数。"""
        return {
            'model_file': self.config.get(
                'PodMeasurement', 'model_file', fallback='pod_seg.pt'
            ),
            'pixel_to_cm': self.config.getfloat(
                'PodMeasurement', 'pixel_to_cm', fallback=0.007433
            ),
            'imgsz': self.config.getint(
                'PodMeasurement', 'imgsz', fallback=1024
            ),
            'confidence': self.config.getfloat(
                'PodMeasurement', 'confidence', fallback=0.25
            ),
            'iou': self.config.getfloat(
                'PodMeasurement', 'iou', fallback=0.70
            ),
            'class_id': self.config.getint(
                'PodMeasurement', 'class_id', fallback=0
            ),
            'refine_boundary': self.config.getboolean(
                'PodMeasurement', 'refine_boundary', fallback=False
            ),
            'refine_margin_ratio': self.config.getfloat(
                'PodMeasurement', 'refine_margin_ratio', fallback=0.004
            ),
            'minimum_color_separation': self.config.getfloat(
                'PodMeasurement', 'minimum_color_separation', fallback=1.25
            ),
            'minimum_raw_refined_iou': self.config.getfloat(
                'PodMeasurement', 'minimum_raw_refined_iou', fallback=0.95
            ),
            'minimum_edge_score_gain': self.config.getfloat(
                'PodMeasurement', 'minimum_edge_score_gain', fallback=0.12
            ),
            'minimum_area_ratio': self.config.getfloat(
                'PodMeasurement', 'minimum_area_ratio', fallback=0.85
            ),
            'maximum_area_ratio': self.config.getfloat(
                'PodMeasurement', 'maximum_area_ratio', fallback=1.15
            ),
        }

    def set_pod_measurement_config(self, **kwargs):
        """保存豆荚测量参数。"""
        if 'PodMeasurement' not in self.config:
            self.config['PodMeasurement'] = {}
        for key, value in kwargs.items():
            if key in {
                'model_file', 'pixel_to_cm', 'imgsz', 'confidence', 'iou',
                'class_id', 'refine_boundary', 'refine_margin_ratio',
                'minimum_color_separation', 'minimum_raw_refined_iou',
                'minimum_edge_score_gain', 'minimum_area_ratio',
                'maximum_area_ratio'
            }:
                self.config['PodMeasurement'][key] = str(value)
        self.save()
    
    # ========== 路径配置 ==========
    def get_paths_config(self):
        """获取路径配置"""
        config_root = os.path.dirname(os.path.abspath(self.config_path))

        def writable_value(option):
            value = self.config.get('Paths', option)
            return value if os.path.isabs(value) else os.path.join(config_root, value)

        return {
            'models_folder': self.config.get('Paths', 'models_folder'),
            'images_folder': writable_value('images_folder'),
            'processed_folder': writable_value('processed_folder'),
            'data_file': writable_value('data_file')
        }
    
    def get(self, section, option, fallback=None):
        """通用获取方法"""
        return self.config.get(section, option, fallback=fallback)
    
    def getint(self, section, option, fallback=None):
        """获取整数"""
        return self.config.getint(section, option, fallback=fallback)
    
    def getfloat(self, section, option, fallback=None):
        """获取浮点数"""
        return self.config.getfloat(section, option, fallback=fallback)
    
    def getboolean(self, section, option, fallback=None):
        """获取布尔值"""
        return self.config.getboolean(section, option, fallback=fallback)

