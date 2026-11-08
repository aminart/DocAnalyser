"""Questions sur les documents d'une analyse (RAG par mots-clés, sans dépendance supplémentaire).

1. Les documents sont découpés en passages courts (une dizaine de lignes) qui gardent leurs repères
   (L12, §4, 00:01:10, Page 3, Slide 2), ceux qu'utilise déjà la vérification des sources.
2. Si tout le corpus tient dans le budget d'une question, il est envoyé en entier : rien ne peut manquer.
   Sinon, les passages sont classés par BM25 sur la question, enrichie de synonymes proposés par le modèle
   (la recherche par mots-clés ne connaît pas les reformulations), et les meilleurs remplissent le budget.
3. Le modèle répond uniquement à partir de ces passages, en citant chaque affirmation [[document | repère]] ;
   les repères cités sont vérifiés dans les documents, comme ceux des synthèses.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.services import analysis_service as svc
from app.services import llm_client, store
from app.services.source_lookup import doc_lines, location_exists

if TYPE_CHECKING:
    from app.services.analysis_service import Analysis, ModelSpec, StoredDocument

logger = logging.getLogger("analyse")

PASSAGE_CHARS = 900  # taille cible d'un passage
OVERLAP_LINES = 2  # lignes reprises d'un passage au suivant, pour ne pas couper une idée
HISTORY_TURNS = 3  # échanges précédents rappelés au modèle (questions de suivi : « et pour lui ? »)
HISTORY_ANSWER_CHARS = 1500
MAX_KEYWORDS = 12
NO_ANSWER = "Les documents ne permettent pas de répondre à cette question."

_TOKEN = re.compile(r"\w+")
_CITATION = re.compile(r"\[\[([^\[\]|]+?)\s*\|\s*([^\[\]]+?)\]\]")
_STOPWORDS = set("""
au aux avec ce ces cet cette dans de des du elle elles en est et etre eu il ils je la le les leur leurs lui ma mais
me meme mes moi mon ne nos notre nous on ont ou par pas pour qu que qui sa se ses son sont sur ta te tes toi ton tu
un une vos votre vous y a l d j m n s t c qu est ete etaient etait sont sera ont avait avoir fait faire plus moins
tres comme si tout tous toute toutes aussi alors donc car quel quelle quels quelles quoi comment pourquoi quand
combien dont cela ca ceci celui celle ceux celles entre vers chez sans sous apres avant
the a an and or of to in on for with by at from is are was were be been it its this that these those what which
who whom how why when where do does did have has had not no can could would should will about into than then there
""".split())


class QuestionError(svc.AnalysisError):
    """Erreur remontée telle quelle à l'interface."""


class QuestionBusy(QuestionError):
    """Une réponse est déjà en cours pour cette analyse."""


# ---------------------------------------------------------------------------
# Passages et index BM25
# ---------------------------------------------------------------------------

@dataclass
class Passage:
    document: str
    location: str  # repère cité par le modèle : « L12-24 », « §3-5 », « Page 3 », « 00:01:10 »
    text: str  # lignes avec leur repère, telles qu'envoyées au modèle
    order: int  # position dans le corpus, pour remettre les passages retenus dans l'ordre de lecture

    def segment(self) -> str:
        return f"[SOURCE: {self.document} | LOC: {self.location}]\n{self.text}\n"


def _span(first: str, last: str) -> str:
    if first == last:
        return first
    prefix = re.match(r"^[L§]", first)
    return f"{first}-{last[1:] if prefix and last.startswith(prefix.group(0)) else last}"


def passages_of(doc: "StoredDocument", start_order: int = 0) -> list[Passage]:
    """Découpe un document en passages courts, sans jamais mélanger deux pages ou deux slides."""
    out: list[Passage] = []
    lines = doc_lines(doc)
    i = 0
    while i < len(lines):
        anchor = lines[i].anchor
        paged = lines[i].ref != anchor  # page PDF ou slide : repère de la page, lignes non numérotées
        j, size = i, 0
        while j < len(lines) and (j == i or size < PASSAGE_CHARS):
            if paged and lines[j].anchor != anchor or not paged and lines[j].ref != lines[j].anchor:
                break
            size += len(lines[j].text) + 8
            j += 1
        window = lines[i:j]
        if paged:
            text, location = "\n".join(ln.text for ln in window), anchor
        else:
            text = "\n".join(f"{ln.ref}: {ln.text}" for ln in window)
            location = _span(window[0].ref, window[-1].ref)
        out.append(Passage(doc.name, location, text, start_order + len(out)))
        if j >= len(lines):
            break
        # Recouvrement de quelques lignes, sauf au changement de page
        same_page = not (paged and lines[j].anchor != anchor)
        i = j - OVERLAP_LINES if same_page and j - i > 2 * OVERLAP_LINES else j
    return out


def _fold(word: str) -> str:
    word = unicodedata.normalize("NFKD", word.lower())
    word = "".join(c for c in word if not unicodedata.combining(c))
    if len(word) > 4 and word.endswith(("s", "x")):
        word = word[:-1]  # pluriels : « parcours », « frictions » / « friction »
    return word


def tokens(text: str) -> list[str]:
    out = []
    for raw in _TOKEN.findall(text):
        w = _fold(raw)
        if len(w) >= 2 and w not in _STOPWORDS and not re.fullmatch(r"l\d+|\d{1,2}", w):
            out.append(w)
    return out


class BM25:
    K1, B = 1.5, 0.75

    def __init__(self, passages: list[Passage]) -> None:
        self.passages = passages
        self.docs = [Counter(tokens(p.text)) for p in passages]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter[str] = Counter()
        for c in self.docs:
            df.update(c.keys())
        n = len(passages)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def scores(self, weighted_terms: dict[str, float]) -> list[float]:
        out = []
        for counts, length in zip(self.docs, self.lengths):
            s = 0.0
            for term, weight in weighted_terms.items():
                tf = counts.get(term)
                if not tf:
                    continue
                norm = tf + self.K1 * (1 - self.B + self.B * length / (self.avg or 1))
                s += weight * self.idf[term] * tf * (self.K1 + 1) / norm
            out.append(s)
        return out


_INDEX: dict[tuple[str, ...], BM25] = {}


def index_for(documents: list["StoredDocument"]) -> BM25:
    key = tuple(d.id for d in documents)
    if key not in _INDEX:
        passages: list[Passage] = []
        for d in documents:
            passages += passages_of(d, len(passages))
        _INDEX[key] = BM25(passages)
    return _INDEX[key]


def budget_chars(spec: "ModelSpec") -> int:
    """Taille des extraits envoyés pour une question : QA_CONTEXT_TOKENS, sans dépasser la fenêtre du modèle."""
    window = max(4_000, spec.context_tokens - svc.RESERVED_TOKENS)
    return int(min(settings.QA_CONTEXT_TOKENS, window) * svc.CHARS_PER_TOKEN)


def select_passages(index: BM25, weighted_terms: dict[str, float], budget: int) -> list[Passage]:
    """Meilleurs passages selon BM25 jusqu'au budget, remis dans l'ordre de lecture."""
    scores = index.scores(weighted_terms)
    ranked = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: scores[i], reverse=True)
    chosen, used, seen_lines = [], 0, set()
    for i in ranked:
        p = index.passages[i]
        size = len(p.segment())
        if used + size > budget:
            if used:
                continue  # un passage plus court peut encore tenir
            break
        # Recouvrement : un passage dont toutes les lignes sont déjà retenues n'apporte rien.
        lines = {(p.document, ln) for ln in p.text.splitlines()}
        if lines <= seen_lines:
            continue
        seen_lines |= lines
        chosen.append(p)
        used += size
    return sorted(chosen, key=lambda p: p.order)


def query_terms(question: str, keywords: list[str], previous: str = "") -> dict[str, float]:
    """Mots de la question (poids 1), synonymes du modèle (0,6), question précédente (0,4) pour les suivis."""
    terms: dict[str, float] = {}
    for words, weight in ((tokens(previous), 0.4), (tokens(" ".join(keywords)), 0.6), (tokens(question), 1.0)):
        for w in words:
            terms[w] = max(terms.get(w, 0.0), weight)
    return terms


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

KEYWORDS_PROMPT = (
    "Tu aides un moteur de recherche par mots-clés à retrouver, dans des documents, les passages qui répondent à "
    "une question. Donne au plus 12 mots-clés à chercher : les mots importants de la question, leurs synonymes, "
    "les formulations proches qu'emploieraient les documents, dans la langue des documents (et en anglais si la "
    "question est en anglais). Mots simples ou expressions courtes, sans phrase. "
    'Réponds uniquement avec un objet JSON : {"keywords": ["...", "..."]}'
)

ANSWER_PROMPT = f"""Tu réponds à une question sur un corpus de documents, à partir des seuls extraits fournis.

Règles de fidélité, à respecter strictement :
- Ne t'appuie que sur les extraits. N'ajoute aucune connaissance extérieure, aucune supposition, aucun chiffre ni nom absent des extraits.
- Si les extraits ne permettent pas de répondre, réponds exactement : « {NO_ANSWER} » puis, en une phrase, ce qu'ils abordent de plus proche s'il y en a.
- Si les extraits ne répondent qu'en partie, réponds à cette partie et dis clairement ce qui manque.
- Si les documents se contredisent, présente chaque position avec sa source.
- Cite la source de chaque affirmation juste après elle, au format [[nom exact du document | repère]]. Le repère est celui de la ligne qui porte l'information (L12, §4, 00:01:10) ou, pour une page ou une slide, son repère (Page 3, Slide 2). Plusieurs sources : [[a.docx | L4]] [[b.pdf | Page 2]].
- Un verbatim se met entre guillemets « » et doit être recopié mot pour mot.

Forme : réponds dans la langue de la question, de façon directe et concise (la réponse d'abord, puis les précisions utiles). Markdown simple autorisé : paragraphes, listes à puces, **gras**. Pas de titre."""


def _answer_user(question: str, segments: list[str], history: list[dict[str, Any]], full: bool) -> str:
    parts = []
    if history:
        parts.append("Échanges précédents (pour comprendre une question de suivi ; leurs sources restent à vérifier "
                     "dans les extraits) :")
        for turn in history:
            parts.append(f"Q : {turn['question']}\nR : {turn['answer'][:HISTORY_ANSWER_CHARS]}")
        parts.append("")
    scope = ("Corpus complet" if full else
             "Extraits retenus par la recherche (le reste du corpus n'est pas fourni : ne conclus pas qu'une "
             "information est absente des documents, seulement des extraits)")
    parts.append(f"{scope} :\n")
    parts.append("\n".join(segments) or "(aucun extrait ne correspond à la question)")
    parts.append(f"\nQuestion : {question}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Appels au modèle
# ---------------------------------------------------------------------------

async def _complete(chain: list["ModelSpec"], system: str, user: str, want_json: bool = False,
                    on_text=None) -> tuple[str, "ModelSpec"]:
    """Modèle de l'analyse, puis les autres modèles du fournisseur en cas de quota ou de surcharge."""
    last: Exception | None = None
    for spec in chain:
        try:
            return await svc._complete(spec, system, user, want_json, on_text), spec
        except (*llm_client.RETRYABLE, llm_client.TimeoutError) as exc:
            last = exc
        except svc.AnalysisError:
            raise
        except Exception as exc:  # noqa: BLE001 : message lisible pour l'interface
            logger.warning("Question : appel à %s refusé : %s", spec.name, exc)
            raise QuestionError(svc._friendly_error(spec, exc)) from exc
    raise QuestionError(svc._friendly_error(chain[-1], last or Exception()))


async def _keywords(chain: list["ModelSpec"], question: str, previous: str) -> list[str]:
    user = f"Question : {question}" + (f"\n(Question précédente, pour le contexte : {previous})" if previous else "")
    try:
        raw, _ = await _complete(chain[:1], KEYWORDS_PROMPT, user, want_json=True)
        words = svc._parse_json(raw).get("keywords")
    except Exception as exc:  # noqa: BLE001 : la recherche se contente alors des mots de la question
        logger.info("Question : mots-clés indisponibles (%s)", exc)
        return []
    return [w.strip() for w in words if isinstance(w, str) and w.strip()][:MAX_KEYWORDS] if isinstance(words, list) else []


def extract_sources(answer: str, documents: list["StoredDocument"]) -> list[dict[str, Any]]:
    """Sources citées dans la réponse, rattachées aux documents réels et vérifiées (repère existant)."""
    names = [d.name for d in documents]
    by_name = {d.name: d for d in documents}
    out, seen = [], set()
    for raw_doc, raw_loc in _CITATION.findall(answer):
        name = svc._match_doc(raw_doc.strip(), names) or raw_doc.strip()
        loc = raw_loc.strip()
        if (name, loc) in seen:
            continue
        seen.add((name, loc))
        doc = by_name.get(name)
        out.append({"document": name, "location": loc, "found": bool(doc and location_exists(doc, loc))})
    return out


# ---------------------------------------------------------------------------
# Questions d'une analyse
# ---------------------------------------------------------------------------

_TASKS: dict[str, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ask(analysis: "Analysis", question: str) -> dict[str, Any]:
    question = question.strip()
    if not question:
        raise QuestionError("Posez une question.")
    if not analysis.documents:
        raise QuestionError("Les documents de cette analyse ne sont plus disponibles.")
    if any(q["status"] == "running" for q in analysis.questions):
        raise QuestionBusy("Une réponse est déjà en cours de rédaction : attendez qu'elle se termine.")
    spec = svc.get_model(analysis.active_model_id or analysis.model_id)
    if not svc.is_configured(spec):
        raise QuestionError(f"Le modèle {spec.name} de cette analyse n'est plus configuré : vérifiez l'onglet Réglages.")
    item: dict[str, Any] = {
        "id": str(uuid.uuid4()), "question": question, "answer": "", "status": "running", "error": None,
        "sources": [], "scope": "", "passages": 0, "keywords": [], "model_name": spec.name, "created_at": _now(),
    }
    analysis.questions.append(item)
    store.save_analysis(analysis)
    _TASKS[analysis.id] = asyncio.create_task(_answer(analysis, item, spec))
    return item


async def _answer(analysis: "Analysis", item: dict[str, Any], spec: "ModelSpec") -> None:
    chain = svc.fallback_chain(spec)
    history = [q for q in analysis.questions if q["status"] == "done" and q is not item][-HISTORY_TURNS:]
    previous = history[-1]["question"] if history else ""
    try:
        index = index_for(analysis.documents)
        whole = [b.to_prompt_segment() for d in analysis.documents for b in d.blocks]
        if sum(map(len, whole)) <= budget_chars(spec):
            # Le corpus tient dans le budget : envoyé en entier, rien ne peut manquer à la réponse.
            item["scope"], item["passages"] = "full", len(index.passages)
            user = _answer_user(item["question"], whole, history, full=True)
        else:
            item["scope"] = "search"
            item["keywords"] = await _keywords(chain, item["question"], previous)
            terms = query_terms(item["question"], item["keywords"], previous)
            selected = select_passages(index, terms, budget_chars(spec))
            item["passages"] = len(selected)
            user = _answer_user(item["question"], [p.segment() for p in selected], history, full=False)

        def on_text(text: str) -> None:
            item["answer"] = text

        answer, used = await _complete(chain, ANSWER_PROMPT, user, on_text=on_text)
        item["answer"] = answer.strip()
        item["model_name"] = used.name
        item["sources"] = extract_sources(item["answer"], analysis.documents)
        item["status"] = "done"
    except asyncio.CancelledError:
        item["status"], item["error"] = "failed", "Question annulée."
    except svc.AnalysisError as exc:
        item["status"], item["error"] = "failed", str(exc)
    except Exception as exc:  # noqa: BLE001 : erreur inattendue, affichée telle quelle
        logger.exception("Question : erreur inattendue")
        item["status"], item["error"] = "failed", f"Erreur inattendue : {str(exc)[:300]}"
    finally:
        _TASKS.pop(analysis.id, None)
        if analysis.id in svc.ANALYSES and item in analysis.questions:
            store.save_analysis(analysis)


def clear(analysis: "Analysis") -> None:
    task = _TASKS.pop(analysis.id, None)
    if task:
        task.cancel()
    analysis.questions.clear()
    store.save_analysis(analysis)
