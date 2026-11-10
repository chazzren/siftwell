# PyInstaller spec for the Windows program (one-folder bundle: dist/Siftwell/Siftwell.exe plus _internal/).
#
#   python -m PyInstaller --noconfirm --clean --distpath <out>/dist --workpath <out>/build installer/siftwell.spec
#
# One windowed exe (no console): no argument opens the window; --server, --jobfinder, --tray, --update, --stop run
# the other entry points (see frozen.py). A one-folder bundle starts faster than one-file and trips fewer antivirus
# false positives. Every top-level .py of the app is bundled (the server loads some of them by name at run time).
import glob
import os

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
nums = [int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:3]] + [0]

hidden = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "*.py"))]
datas, binaries = [], []
for pkg in ("webview", "pystray", "pillow_heif"):          # window, tray icon, HEIC photos
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hidden += h

for name in ("assets", "packs"):
    datas.append((os.path.join(ROOT, name), name))
for name in ("VERSION", "README.md", "LICENSE", "config.default.json"):
    datas.append((os.path.join(ROOT, name), "."))

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=tuple(nums), prodvers=tuple(nums), mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
    kids=[StringFileInfo([StringTable("040904B0", [
        StringStruct("CompanyName", "Siftwell"),
        StringStruct("FileDescription", "Siftwell"),
        StringStruct("FileVersion", VERSION),
        StringStruct("InternalName", "Siftwell"),
        StringStruct("OriginalFilename", "Siftwell.exe"),
        StringStruct("ProductName", "Siftwell"),
        StringStruct("ProductVersion", VERSION)])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])])])

a = Analysis(
    [os.path.join(ROOT, "app_window.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "test", "unittest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts,
    [("X utf8", None, "OPTION")],        # always UTF-8 mode (the data files are UTF-8)
    exclude_binaries=True,
    name="Siftwell",
    icon=os.path.join(ROOT, "assets", "brand", "siftwell.ico"),
    console=False,
    upx=False,
    version=version_info,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Siftwell", upx=False)
