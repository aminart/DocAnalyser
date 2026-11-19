"""Images des documents, pour les faire lire par un modèle qui voit les images (facultatif).

À l'import, les images utiles sont mises de côté : pages scannées d'un PDF (rendues en image), images insérées
dans un PDF, un Word ou un PowerPoint, et fichiers image importés tels quels. Elles ne sont lues qu'au lancement
d'une analyse pour laquelle un modèle de vision a été choisi ; sans lui, l'application fonctionne comme avant,
sur le texte seul.

Chaque image est réduite (1 600 px au plus, JPEG) et rangée sous son empreinte dans STORAGE_DIR/images : la
même image, présente dans deux documents ou importée deux fois, n'est enregistrée qu'une fois.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("analyse")

IMAGE_FORMATS = {".png": "image PNG", ".jpg": "image JPEG", ".jpeg": "image JPEG", ".webp": "image WebP"}
MAX_SIDE = 1600  # pixels : assez pour lire un texte de page, sans alourdir la requête
MIN_SIDE = 120  # plus petit : logo, icône ou puce, sans intérêt pour l'analyse
MAX_IMAGES = 300  # par document
RENDER_SCALE = 2.0  # page scannée rendue à environ 144 ppp


@dataclass
class ExtractedImage:
    location: str  # « Page 12 », « Slide 4 », « Image 3 », « Image »
    data: bytes  # JPEG réduit
    scanned: bool = False  # page entière sans texte (scan), plutôt qu'une image insérée


def images_dir() -> Path:
    return settings.STORAGE_DIR / "images"


def _normalize(raw: bytes | None = None, pil_image=None) -> bytes | None:
    """Image réduite en JPEG ; None si illisible ou trop petite pour être utile."""
    from PIL import Image

    try:
        img = pil_image if pil_image is not None else Image.open(io.BytesIO(raw or b""))
        img.load()
        if min(img.size) < MIN_SIDE:
            return None
        if img.mode not in ("RGB", "L"):
            background = Image.new("RGB", img.size, "white")  # transparence : fond blanc, comme sur la page
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:  # format d'image exotique ou fichier abîmé : l'image est ignorée
        return None


def is_image(raw: bytes) -> bool:
    from PIL import Image

    try:
        Image.open(io.BytesIO(raw)).verify()
        return True
    except Exception:
        return False


def extract(path: Path, name: str, empty_pages: list[int] | None = None) -> list[ExtractedImage]:
    """Images utiles d'un document ; une erreur de lecture ne fait jamais échouer l'import."""
    suffix = Path(name).suffix.lower()
    try:
        if suffix in IMAGE_FORMATS:
            data = _normalize(path.read_bytes())
            return [ExtractedImage("Image", data, scanned=True)] if data else []
        if suffix == ".pdf":
            return _pdf(path, set(empty_pages or []))
        if suffix == ".pptx":
            return _pptx(path)
        if suffix == ".docx":
            return _docx(path)
    except Exception as exc:  # bibliothèque absente, document inhabituel : on garde le texte seul
        logger.warning("Images de %s non extraites : %s", name, exc)
    return []


def _pdf(path: Path, empty_pages: set[int]) -> list[ExtractedImage]:
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c
    except ImportError:
        return []
    out: list[ExtractedImage] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for i in range(len(pdf)):
            if len(out) >= MAX_IMAGES:
                break
            page = pdf[i]
            if i + 1 in empty_pages:  # page scannée : la page entière est lue
                data = _normalize(pil_image=page.render(scale=RENDER_SCALE).to_pil())
                if data:
                    out.append(ExtractedImage(f"Page {i + 1}", data, scanned=True))
                continue
            for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=3):
                try:
                    data = _normalize(pil_image=obj.get_bitmap(render=True).to_pil())
                except Exception:
                    data = None
                if data:
                    out.append(ExtractedImage(f"Page {i + 1}", data))
    finally:
        pdf.close()
    return out


def _pptx(path: Path) -> list[ExtractedImage]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    out: list[ExtractedImage] = []

    def walk(shapes, slide_no: int) -> None:
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                walk(shape.shapes, slide_no)
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE and len(out) < MAX_IMAGES:
                data = _normalize(shape.image.blob)
                if data:
                    out.append(ExtractedImage(f"Slide {slide_no}", data))

    for i, slide in enumerate(Presentation(str(path)).slides, start=1):
        walk(slide.shapes, i)
    return out


def _docx(path: Path) -> list[ExtractedImage]:
    from docx import Document

    doc = Document(str(path))
    out: list[ExtractedImage] = []
    seen: set[str] = set()
    # Ordre d'apparition dans le texte : chaque image est appelée par son identifiant de relation.
    for blip in doc.element.body.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
        rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
        if not rid or rid in seen or len(out) >= MAX_IMAGES:
            continue
        seen.add(rid)
        part = doc.part.related_parts.get(rid)
        data = _normalize(getattr(part, "blob", None)) if part is not None else None
        if data:
            out.append(ExtractedImage(f"Image {len(out) + 1}", data))
    return out


def save(images: list[ExtractedImage]) -> list[dict]:
    """Enregistre les images sous leur empreinte ; renvoie les références gardées avec le document."""
    images_dir().mkdir(parents=True, exist_ok=True)
    refs = []
    for img in images:
        digest = hashlib.sha256(img.data).hexdigest()
        target = images_dir() / f"{digest}.jpg"
        if not target.exists():
            target.write_bytes(img.data)
        refs.append({"location": img.location, "file": target.name, "scanned": img.scanned, "done": False})
    return refs


def load(ref: dict) -> bytes | None:
    try:
        return (images_dir() / Path(ref["file"]).name).read_bytes()
    except (OSError, KeyError):
        return None


def purge(referenced: set[str]) -> None:
    """Supprime les images qu'aucun document ne cite plus (appelé au démarrage)."""
    try:
        for f in images_dir().glob("*.jpg"):
            if f.name not in referenced:
                f.unlink(missing_ok=True)
    except OSError:
        pass


_NUM = re.compile(r"^(?:Page|Slide) (\d+)$")


def number(location: str) -> int | None:
    m = _NUM.match(location)
    return int(m.group(1)) if m else None
