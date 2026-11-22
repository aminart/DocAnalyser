# Recette PyInstaller de DocAnalyser.exe (Windows) et DocAnalyser.app (Mac) : workflows « Build Windows exe » et
# « Build macOS app », ou à la main : pyinstaller --noconfirm DocAnalyser.spec (sur la machine visée).
# Prérequis : l'interface compilée (cd frontend && npm ci && npm run build).
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Version : fichier VERSION (source unique), embarqué et affiché dans Propriétés > Détails sous Windows
# (cette ressource demande les modules Windows de PyInstaller).
VERSION = Path("VERSION").read_text(encoding="utf-8").strip()
try:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )
except ImportError:  # hors Windows : pas de ressource de version, la fabrication continue
    version_info = None
else:
    _nombres = tuple(int(partie) for partie in VERSION.split("-")[0].split(".")) + (0,)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=_nombres[:4], prodvers=_nombres[:4]),
        kids=[
            StringFileInfo([StringTable("040C04B0", [
                StringStruct("ProductName", "DocAnalyser"),
                StringStruct("FileDescription", "DocAnalyser - synthèse de documents par thèmes"),
                StringStruct("ProductVersion", VERSION),
                StringStruct("FileVersion", VERSION),
                StringStruct("OriginalFilename", "DocAnalyser.exe"),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x040C, 1200])]),
        ],
    )

if not Path("frontend/dist/index.html").is_file():
    raise SystemExit("Interface absente : lancer d'abord « npm ci && npm run build » dans frontend/.")

datas = [
    ("VERSION", "."),
    ("frontend/dist", "frontend_dist"),
    ("backend/app/assets/fonts", "app/assets/fonts"),  # police Unicode de l'export PDF
]
binaries = []
hiddenimports = collect_submodules("uvicorn") + collect_submodules("app")

# Lecture des documents et exports : bibliothèques avec données (pdfminer : tables de caractères des PDF)
for paquet in ("pdfminer", "pypdfium2", "pypdfium2_raw", "docx", "pptx", "openpyxl", "fpdf"):
    try:
        paquet_datas, paquet_binaries, paquet_hidden = collect_all(paquet)
    except Exception:  # noqa: BLE001 : paquet absent
        continue
    datas += paquet_datas
    binaries += paquet_binaries
    hiddenimports += paquet_hidden

a = Analysis(
    ["backend/launcher.py"],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # Inutiles ici (des Mo pour rien) : boucle uvloop (Linux), rechargement à chaud, yaml, numpy/pandas
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "fitz", "pymupdf", "uvloop", "watchfiles", "yaml",
              "numpy", "pandas"],
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # Mac : application DocAnalyser.app (dossier, plus rapide à démarrer qu'un exécutable unique), signée
    # localement (« ad hoc ») par PyInstaller : sans compte Apple Developer, ni signature d'éditeur ni notarisation.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="DocAnalyser",
        console=False,
        argv_emulation=False,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="DocAnalyser", upx=False)
    app = BUNDLE(
        coll,
        name="DocAnalyser.app",
        icon=os.path.join(SPECPATH, "icone", "docanalyser.icns"),
        bundle_identifier="io.github.aminart.docanalyser",
        version=VERSION,
        info_plist={
            "CFBundleName": "DocAnalyser",
            "CFBundleDisplayName": "DocAnalyser",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "DocAnalyser - synthèse de documents par thèmes",
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="DocAnalyser",
        icon=os.path.join(SPECPATH, "icone", "docanalyser.ico"),
        version=version_info,
        console=True,
        upx=False,
    )
