# Recette PyInstaller de DocAnalyser.exe (workflow « Build Windows exe », ou : pyinstaller --noconfirm DocAnalyser.spec).
# Prérequis : l'interface compilée (cd frontend && npm ci && npm run build).
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
]
binaries = []
hiddenimports = collect_submodules("uvicorn") + collect_submodules("app")

# Lecture des documents et exports : bibliothèques avec données ou modules natifs
for paquet in ("pymupdf", "fitz", "docx", "pptx", "openpyxl", "fpdf"):
    try:
        paquet_datas, paquet_binaries, paquet_hidden = collect_all(paquet)
    except Exception:  # noqa: BLE001 : nom de paquet absent selon la version de PyMuPDF
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
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DocAnalyser",
    version=version_info,
    console=True,
    upx=False,
)
