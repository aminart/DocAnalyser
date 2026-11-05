"""Prépare une nouvelle version de DocAnalyser.

    python scripts/bump_version.py 1.1.0        # numéro explicite
    python scripts/bump_version.py patch|minor|major

Met à jour le fichier VERSION (source unique), la version du frontend (package.json et
package-lock.json) et transforme la section « Non publié » du CHANGELOG en section datée.
Ne commit rien et ne crée pas de release : voir README, « Versions ».
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
CHANGELOG = ROOT / "CHANGELOG.md"
PACKAGE_FILES = [ROOT / "frontend" / "package.json", ROOT / "frontend" / "package-lock.json"]
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
UNRELEASED = "## [Non publié]"


def next_version(current: str, wanted: str) -> str:
    match = SEMVER.match(current)
    if not match:
        raise SystemExit(f"Version actuelle illisible dans VERSION : {current!r}")
    major, minor, patch = map(int, match.groups())
    if wanted == "major":
        return f"{major + 1}.0.0"
    if wanted == "minor":
        return f"{major}.{minor + 1}.0"
    if wanted == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if not SEMVER.match(wanted):
        raise SystemExit(f"Numéro invalide : {wanted!r} (attendu : X.Y.Z, patch, minor ou major)")
    if tuple(map(int, wanted.split("."))) <= (major, minor, patch):
        raise SystemExit(f"{wanted} n'est pas supérieure à la version actuelle {current}")
    return wanted


def update_package_files(version: str) -> None:
    for path in PACKAGE_FILES:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = version
        if path.name == "package-lock.json" and "" in data.get("packages", {}):
            data["packages"][""]["version"] = version
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_changelog(version: str, today: dt.date) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    if UNRELEASED not in text:
        raise SystemExit("CHANGELOG.md : section « ## [Non publié] » introuvable.")
    head, rest = text.split(UNRELEASED, 1)
    body = rest.split("\n## ", 1)[0]
    if not body.strip():
        raise SystemExit("CHANGELOG.md : la section « Non publié » est vide, rien à publier.")
    text = head + f"{UNRELEASED}\n\n## [{version}] — {today.isoformat()}" + rest
    CHANGELOG.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> None:
    if len(argv) != 1:
        raise SystemExit(__doc__)
    current = VERSION_FILE.read_text(encoding="utf-8").strip()
    version = next_version(current, argv[0])
    update_changelog(version, dt.date.today())
    VERSION_FILE.write_text(version + "\n", encoding="utf-8")
    update_package_files(version)
    print(f"DocAnalyser {current} → {version}")
    print("Ensuite : relire CHANGELOG.md, committer, fusionner sur main, puis créer la release "
          f"v{version} sur GitHub (DocAnalyser-X.Y.Z.exe y est joint automatiquement).")


if __name__ == "__main__":
    main(sys.argv[1:])
