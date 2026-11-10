# PyInstaller spec for the Mac app: dist/Siftwell.app (a windowed one-folder bundle, built on Apple silicon).
#
#   python -m PyInstaller --noconfirm --clean --distpath <out>/dist --workpath <out>/build installer/siftwell-mac.spec
#
# Same program as the Windows build (installer/siftwell.spec): no argument opens the window; --server, --jobfinder,
# --tray, --update, --stop run the other entry points (see frozen.py). Every top-level .py of the app is bundled (the
# server loads some of them by name at run time). pywebview uses WKWebView through PyObjC, pystray draws the menu-bar
# icon through PyObjC too, so both are collected whole. The app is not signed with a developer certificate (PyInstaller
# gives the arm64 binaries an ad-hoc signature, which is all Apple silicon requires to run); build_mac.sh makes the .dmg.
import glob
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
BUNDLE_ID = "io.github.chazzren.siftwell"

hidden = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "*.py"))]
datas, binaries = [], []
for pkg in ("webview", "pystray"):                          # window and menu-bar icon
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hidden += h
for pkg in ("AppKit", "Foundation", "WebKit", "Quartz", "objc", "PyObjCTools", "CoreFoundation", "Cocoa", "UserNotifications", "Security", "Carbon"):
    try:
        hidden += collect_submodules(pkg)
    except Exception:
        pass

for name in ("assets", "packs"):
    datas.append((os.path.join(ROOT, name), name))
for name in ("VERSION", "README.md", "LICENSE", "config.default.json"):
    datas.append((os.path.join(ROOT, name), "."))

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
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Siftwell", upx=False)
app = BUNDLE(
    coll,
    name="Siftwell.app",
    icon=os.path.join(ROOT, "assets", "brand", "siftwell.icns"),
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        "CFBundleName": "Siftwell",
        "CFBundleDisplayName": "Siftwell",
        "CFBundleExecutable": "Siftwell",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": False,                       # a normal app with a Dock icon (the menu-bar helper hides its own, see tray.py)
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Siftwell, MIT license",
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},   # the window shows http://127.0.0.1:<port>
        "NSLocalNetworkUsageDescription": "Siftwell shows your job board to your phone on your home Wi-Fi when you turn that on.",
    },
)
