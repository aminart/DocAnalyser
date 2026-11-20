"""Lecture des images des documents par un modèle qui voit les images, au début d'une analyse.

Facultatif : sans modèle de vision choisi au lancement, rien ne change (analyse du texte seul). Avec lui, chaque
image mise de côté à l'import (image_reader) est transcrite ou décrite, puis ajoutée au document comme un bloc de
texte à son repère d'origine (« Page 12 », « Slide 4 », « Image 3 ») : le reste de l'analyse, les sources et
leur vérification fonctionnent comme pour le texte. Une image déjà lue par le même modèle n'est pas redemandée.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from typing import Any

from app.services import analysis_service as svc
from app.services import batch_pipeline, image_reader, llm_client, store

logger = logging.getLogger("analyse")

VISION_PROMPT = (
    "Tu lis une image tirée d'un document professionnel : page scannée, schéma, graphique, photo de tableau "
    "blanc, capture d'écran. Transcris fidèlement tout le texte lisible, dans l'ordre de lecture, sans rien "
    "inventer, résumer ni corriger. Pour un tableau, écris une ligne par rangée, cellules séparées par « | ». "
    "Pour un schéma ou un graphique, décris ensuite en quelques phrases factuelles ce qu'il montre (éléments, "
    "liens, valeurs et unités lisibles). Pour une photo sans texte, une phrase de description suffit. Si l'image "
    "est purement décorative (logo, icône, fond, filigrane), réponds exactement : RIEN. Réponds en texte brut, "
    "sans commentaire ni introduction."
)
NOTHING = "RIEN"
RETRY_WAITS = (5, 20)

PREFIX = {
    "scanned_page": "[Page scannée, lue par le modèle de vision]",
    "image_file": "[Image, lue par le modèle de vision]",
    "embedded": "[Image du document, décrite par le modèle de vision]",
}


class VisionUnsupported(Exception):
    """Le modèle refuse les images : inutile d'envoyer les suivantes."""


def _prefix(ref: dict[str, Any]) -> str:
    if ref.get("scanned"):
        return PREFIX["scanned_page"] if ref["location"].startswith("Page") else PREFIX["image_file"]
    return PREFIX["embedded"]


def _stop_if_looping(text: str) -> None:
    """Transcription d'image qui répète le même passage sans fin : interrompue (l'image est comptée en échec)."""
    if svc.looping(text):  # quelques Ko par image : vérifier à chaque morceau reste négligeable
        raise svc.InvalidModelOutput("Transcription interrompue : le modèle répétait le même passage en boucle.")


async def _read_one(spec: svc.ModelSpec, data: bytes, label: str) -> str:
    prov = spec.provider
    extra, system = svc._thinking_off(spec, VISION_PROMPT)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": label},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(data).decode()}},
        ]},
    ]
    last: Exception | None = None
    for wait in (0, *RETRY_WAITS):
        if wait:
            await asyncio.sleep(wait)
        try:
            text, _ = await llm_client.chat(
                base_url=prov.api_base, api_key=prov.api_key, model=spec.name, messages=messages, temperature=0,
                max_tokens=svc._max_output(prov), ca_bundle=prov.ca_bundle, stream=True, extra=extra,
                timeout=svc.request_timeout(spec, streaming=True), on_delta=_stop_if_looping,
            )
            return svc._THINK.sub("", text).strip()
        except llm_client.RETRYABLE as exc:
            last = exc
        except llm_client.LLMError as exc:  # clé refusée, modèle inconnu, images refusées…
            raise VisionUnsupported(str(exc)[:200]) from exc
    raise last or RuntimeError("échec de lecture")


def _insert(doc: svc.StoredDocument, block: svc.AnchoredTextBlock) -> None:
    """Ajoute le bloc à sa place : après la page (ou slide) qu'il illustre, sinon en fin de document."""
    n = image_reader.number(block.location)
    if n is None:
        doc.blocks.append(block)
        return
    pos = 0
    for k, b in enumerate(doc.blocks):
        m = image_reader.number(b.location)
        if m is not None and m <= n:
            pos = k + 1
    doc.blocks.insert(pos, block)


async def read_images(analysis: svc.Analysis) -> None:
    pending = [(doc, ref) for doc in analysis.documents for ref in doc.images if not ref.get("done")]
    if not pending:
        return
    spec = svc.get_model(analysis.vision_model_id)
    total, done, failed = len(pending), 0, 0
    stopped: str | None = None
    touched: set[str] = set()

    def note() -> None:
        analysis.step_notes[0] = f"Lecture des images par {spec.name} : {done}/{total}"
        analysis.progress = 14 * done / total

    async def one(doc: svc.StoredDocument, ref: dict[str, Any]) -> None:
        nonlocal done, failed, stopped
        if stopped:
            return
        data = image_reader.load(ref)
        key = hashlib.sha256(f"{spec.provider.api_base}\0{spec.name}\0{VISION_PROMPT}\0{ref['file']}".encode()).hexdigest()
        cached = batch_pipeline._lot_load(key)
        try:
            if cached is not None:
                text = cached.get("text", "")
            elif data is None:
                text = ""  # fichier image disparu : rien à lire
            else:
                text = await _read_one(spec, data, f"Image : {doc.name}, {ref['location']}")
                batch_pipeline._lot_save(key, {"text": text})
        except VisionUnsupported as exc:
            stopped = stopped or str(exc)
            return
        except Exception as exc:  # image trop lourde, délai dépassé… : l'image est passée, l'analyse continue
            logger.warning("Image %s de %s non lue : %s", ref["location"], doc.name, exc)
            failed += 1
            return
        if text and text.strip().rstrip(".").upper() != NOTHING:
            _insert(doc, svc.AnchoredTextBlock(doc.name, ref["location"], f"{_prefix(ref)}\n{text}"))
        ref["done"] = True
        touched.add(doc.id)
        done += 1
        note()

    note()
    await batch_pipeline._gather_limited([one(d, r) for d, r in pending], svc.concurrency(spec))
    for doc in analysis.documents:
        if doc.id in touched:
            store.save_document(doc)

    if stopped:
        analysis.step_notes[0] = (f"{spec.name} n'a pas pu lire les images ({stopped}) : analyse sur le texte seul. "
                                  "Vérifiez que ce modèle voit les images.")
    elif failed:
        analysis.step_notes[0] = f"Images lues par {spec.name} : {done}/{total} ({failed} illisibles, ignorées)"
    else:
        analysis.step_notes[0] = f"Images lues par {spec.name} : {done}/{total}"
