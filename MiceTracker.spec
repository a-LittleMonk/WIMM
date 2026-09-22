# -*- mode: python ; coding: utf-8 -*-
# Optimized one-folder build for fast startup + minimum size without dropping
# any feature. Excludes only modules that the codebase does not import.

block_cipher = None

# Qt modules NOT used by this app — excluding shrinks the Qt5 bundle.
qt_excludes = [
    "PyQt5.QtBluetooth", "PyQt5.QtDBus", "PyQt5.QtDesigner",
    "PyQt5.QtHelp", "PyQt5.QtLocation", "PyQt5.QtMultimedia",
    "PyQt5.QtMultimediaWidgets", "PyQt5.QtNetwork", "PyQt5.QtNfc",
    "PyQt5.QtOpenGL", "PyQt5.QtPositioning", "PyQt5.QtPrintSupport",
    "PyQt5.QtQml", "PyQt5.QtQuick", "PyQt5.QtQuickWidgets",
    "PyQt5.QtRemoteObjects", "PyQt5.QtSensors", "PyQt5.QtSerialPort",
    "PyQt5.QtSql", "PyQt5.QtSvg", "PyQt5.QtTest", "PyQt5.QtWebChannel",
    "PyQt5.QtWebEngine", "PyQt5.QtWebEngineCore", "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtWebKit", "PyQt5.QtWebKitWidgets", "PyQt5.QtWebSockets",
    "PyQt5.QtXml", "PyQt5.QtXmlPatterns", "PyQt5.Qsci",
    "PyQt5.Qt3DAnimation", "PyQt5.Qt3DCore", "PyQt5.Qt3DExtras",
    "PyQt5.Qt3DInput", "PyQt5.Qt3DLogic", "PyQt5.Qt3DRender",
    "PyQt5.QtCharts", "PyQt5.QtDataVisualization",
    "PyQt5.QtTextToSpeech",
]

# Heavy / GUI-only deps the app does not use.
other_excludes = [
    "tkinter", "tcl", "tk", "_tkinter",
    "PySide2", "PySide6", "PyQt6", "shiboken2", "shiboken6",
    "IPython", "ipykernel", "jupyter", "notebook", "nbconvert", "nbformat",
    "pytest", "sphinx", "babel",
    "scipy", "sympy", "statsmodels", "patsy", "h5py", "tables",
    "tensorflow", "torch", "sklearn", "skimage",
    "PIL.ImageQt",  # ImageQt only needed if we used PIL→Qt bridge
    # matplotlib backends we don't use — Qt5Agg is what gets used at runtime,
    # everything else is dead weight.
    "matplotlib.backends.backend_tkagg",
    "matplotlib.backends.backend_tkcairo",
    "matplotlib.backends.backend_wx",
    "matplotlib.backends.backend_wxagg",
    "matplotlib.backends.backend_wxcairo",
    "matplotlib.backends.backend_gtk3agg",
    "matplotlib.backends.backend_gtk3cairo",
    "matplotlib.backends.backend_gtk4agg",
    "matplotlib.backends.backend_gtk4cairo",
    "matplotlib.backends.backend_webagg",
    "matplotlib.backends.backend_nbagg",
    "matplotlib.backends.backend_qt6",
    "matplotlib.backends.backend_qt6agg",
    "matplotlib.backends.backend_qt6cairo",
    "matplotlib.tests",
]

excludes_all = qt_excludes + other_excludes

# Make sure the matplotlib Qt5Agg backend + agg/pdf cores stay in.
hidden_imports = [
    "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_agg",
    "openpyxl.cell._writer",
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes_all,
    noarchive=False,
    optimize=0,  # keep docstrings — numpy.add_docstring requires real strings
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MiceTracker',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        # Don't UPX these — UPX-ing them breaks runtime / signatures.
        "vcruntime140.dll", "vcruntime140_1.dll",
        "python3.dll", "python313.dll",
        "Qt5Core.dll", "Qt5Gui.dll", "Qt5Widgets.dll",
    ],
    name='MiceTracker',
)
