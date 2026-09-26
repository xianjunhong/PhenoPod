# PhenoPod

PhenoPod 是一个基于 PyQt5、海康工业相机和 YOLO 实例分割的单图豆荚形态测量演示项目。项目已固定为单类别 `pod` 模型；拍摄或导入一张照片后，会完成实例分割、逐荚形态计算和叠加可视化。

## 演示能力

- 扫描并打开海康相机，实时预览后“拍照并测量”
- 导入 JPG、PNG、BMP、TIFF、WebP 图像进行离线演示
- 显示每个豆荚的实例掩膜、真实轮廓、端点、弦长、最大内切圆、外弧和最小旋转矩形
- 计算豆荚数量、长度、宽度、内外弧长、曲率、旋转矩形长宽和置信度
- 在界面查看逐荚明细，切换原图/测量图
- 保存原图、结果图和完整逐荚数据，导出 Excel 或 CSV

## 算法流程

1. `models/pod_seg.pt` 输出单类别豆荚实例掩膜。
2. 对每个掩膜保留最大连通域并填充轮廓。
3. 细化掩膜骨架，沿主骨架两端各取总弧长 5% 的窗口拟合切线，向外投射到真实轮廓定位豆荚两端；异常时使用 PCA 回退。
4. 以两端直线距离作为长度，以最大内切圆直径作为宽度。
5. 沿真实轮廓计算内弧、外弧，并计算 `曲率 = 端点弦长 / 外弧长`。
6. 计算最小旋转矩形长宽，生成叠加结果图和统计摘要。

## 启动

```powershell
python -m pip install -r requirements.txt
python start.py
```

Windows 也可以双击 `启动.bat`。

正式交付安装包位于 `dist/installer/PhenoPod_Setup_1.1.1.exe`，包含开始菜单、可选桌面快捷方式和卸载程序。接收方无需安装 Python。海康相机功能仍要求目标电脑安装对应的 MVS 设备驱动，本地图像导入和测量不依赖相机。

重新构建安装包时，在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_setup.ps1
```

打包版的配置、测量图片和记录保存在 `%LOCALAPPDATA%\PhenoPod`。

## 使用

1. 主页进入“豆荚测量”。
2. 点击“扫描设备”并打开相机，或直接点击“导入图片”。
3. 调整分割置信度和像素标定值。
4. 点击“拍照并测量”。
5. 查看可视化与逐荚明细，需要时填写样本编号并保存。

## 标定说明

默认像素标定为 `0.007433 cm/px`，来自原始算法。厘米结果依赖拍摄距离、镜头、分辨率和 ROI；设备布置改变后应使用标定板重新标定，并在测量页或设置页更新该值。

## 关键文件

```text
models/pod_seg.pt                              单类别豆荚实例分割权重
common/pod_measurement.py                      分割结果解析、形态测量和可视化
modules/seed_inspection/inspection_handler.py  设备、推理线程与保存流程
modules/seed_inspection/inspection_home.py     实时演示界面
modules/seed_inspection/inspection_data.py     历史记录与导出
config_new.ini                                 相机、ROI 和算法参数
```

保存数据位于 `data/images`、`data/processed` 和 `data/records.db`。
