# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for MangaTCT.exe - the launcher, and only the launcher.
#
# Built on a Windows runner by `.github/workflows/release.yml`:
#     pyinstaller --clean --noconfirm launcher/MangaTCT.spec
#
# One file, windowed (no console: the launcher has its own small window and
# the editor's output goes to a log). The app itself is NOT in here - it is
# the zip the launcher fetches - so this exe changes only when the launcher
# does, which is rarely.
import os

here = os.path.dirname(os.path.abspath(SPEC))
root = os.path.dirname(here)

a = Analysis(
    [os.path.join(here, "mangatct_launcher.py")],
    pathex=[here],
    binaries=[],
    # The mark, carried inside the exe: the launcher's own window wears it
    # (title bar, taskbar, and beside the name) before any app version is on
    # disk to borrow it from. lee: *"use the logo everywhere"*.
    datas=[(os.path.join(root, "static", "icon.ico"), "."),
           (os.path.join(root, "static", "icon.png"), ".")],
    hiddenimports=["tkinter", "tkinter.ttk"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["numpy", "PIL", "cv2", "torch", "pytest", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MangaTCT",
    icon=os.path.join(root, "static", "icon.ico"),
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=os.path.join(here, "version_info.txt"),
)
