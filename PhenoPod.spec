# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file build definition for PhenoPod."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH)
datas = [
    (str(project_root / "models" / "pod_seg.pt"), "models"),
    (str(project_root / "config_new.ini"), "."),
]
binaries = []
hiddenimports = [
    "openpyxl",
    "ultralytics.models.yolo.segment",
    "ultralytics.models.yolo.segment.predict",
]

for package_name in ("qfluentwidgets",):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

for icon_path in (project_root / "icons").glob("*.png"):
    datas.append((str(icon_path), "icons"))

mvs_runtime = Path(
    r"C:\Program Files (x86)\Common Files\MVS\Runtime\Win64_x64"
)
if mvs_runtime.is_dir():
    for runtime_file in mvs_runtime.iterdir():
        if not runtime_file.is_file():
            continue
        if runtime_file.suffix.lower() in {".dll", ".ax", ".cti"}:
            binaries.append((str(runtime_file), "mvs_runtime"))
        else:
            datas.append((str(runtime_file), "mvs_runtime"))

a = Analysis(
    [str(project_root / "start.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tensorflow",
        "pandas",
        "pyarrow",
        "dask",
        "bokeh",
        "sqlalchemy",
        "numba",
        "llvmlite",
        "h5py",
        "sphinx",
        "docutils",
        "lxml",
        "botocore",
        "zmq",
        "statsmodels",
        "patsy",
        "nbformat",
        "jsonschema",
        "argon2",
        "anyio",
        "paramiko",
        "bcrypt",
        "nacl",
        "cloudpickle",
        "lz4",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PhenoPod",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "icons" / "PhenoPod.ico"),
    version=str(project_root / "version_info.txt"),
)
