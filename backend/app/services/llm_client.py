"""Client minimal pour les API « chat completions » compatibles OpenAI, écrit avec httpx.

Remplace litellm, souvent bloqué par les proxys d'entreprise (erreur 403 à l'installation). Couvre tout ce
dont l'application a besoin : réponse complète ou en streaming, sortie JSON, longueur maximale, certificat
d'entreprise, et des erreurs typées pour les réessais (quota, surcharge, délai…).

Fournisseurs : Mistral, vLLM, Ollama, Azure OpenAI, passerelles internes, ainsi que Gemini et Claude via
leurs points d'accès compatibles OpenAI.
"""
from __future__ import annotations

import json
import ssl
from pathlib import Path
from typing import Any, Callable

import httpx

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
ANTHROPIC_BASE = "https://api.anthropic.com/v1"


class LLMError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class RateLimitError(LLMError):
    """429 : quota ou limite de débit."""


class ServiceUnavailableError(LLMError):
    """5xx, ou connexion impossible : surcharge ou indisponibilité."""


class ConnectionFailedError(ServiceUnavailableError):
    """Serveur injoignable (adresse erronée, Ollama non lancé)."""


class TimeoutError(LLMError):  # noqa: A001 - nom explicite dans ce module
    """Pas de réponse dans le délai."""


class AuthenticationError(LLMError):
    """401 / 403 : clé absente ou refusée."""


class NotFoundError(LLMError):
    """404 : modèle ou adresse inconnus."""


class ContextWindowExceededError(LLMError):
    """Requête plus grande que la fenêtre du modèle."""


class BadRequestError(LLMError):
    """400 / 422 : requête refusée."""


RETRYABLE = (RateLimitError, ServiceUnavailableError, TimeoutError)
STREAM_READ_TIMEOUT = 180.0  # secondes sans nouveau morceau de réponse

_CLIENTS: dict[str, httpx.AsyncClient] = {}


def _client(ca_bundle: str) -> httpx.AsyncClient:
    # Un certificat remplacé depuis l'écran Réglages garde le même chemin : la date du fichier change la clé.
    try:
        key = f"{ca_bundle}@{Path(ca_bundle).stat().st_mtime_ns}" if ca_bundle else "default"
    except OSError:
        key = ca_bundle
    if key not in _CLIENTS:
        timeout = httpx.Timeout(600.0, connect=20.0)
        _CLIENTS[key] = httpx.AsyncClient(verify=verification(ca_bundle), timeout=timeout)
    return _CLIENTS[key]


def verification(ca_bundle: str) -> ssl.SSLContext | bool:
    """Vérification HTTPS : certificats du système, ou l'autorité fournie (certificat d'entreprise).

    Python 3.13 active par défaut une vérification X.509 « stricte » qui refuse les autorités de certification
    internes sans extension « key usage », pourtant courantes en entreprise et acceptées par curl et les
    navigateurs. On la retire : la chaîne de certificats et le nom du serveur restent entièrement vérifiés.
    """
    if not ca_bundle:
        return True
    contexte = ssl.create_default_context(cafile=ca_bundle)
    contexte.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return contexte


def _error(status: int, body: str) -> LLMError:
    try:
        payload = json.loads(body)
        if isinstance(payload, list) and payload:  # Gemini renvoie parfois une liste
            payload = payload[0]
        err = payload.get("error", payload) if isinstance(payload, dict) else {}
        message = err.get("message") if isinstance(err, dict) else None
        message = message or (payload.get("message") if isinstance(payload, dict) else None) or body
    except (json.JSONDecodeError, AttributeError):
        message = body
    message = str(message).strip()[:1500] or f"HTTP {status}"
    lowered = message.lower()
    if status == 429:
        return RateLimitError(message, status)
    if status in (401, 403):
        return AuthenticationError(message, status)
    if status == 404:
        return NotFoundError(message, status)
    if status in (400, 413, 422) and any(k in lowered for k in ("context", "too long", "maximum", "token count", "too large")):
        return ContextWindowExceededError(message, status)
    if status in (400, 413, 422):
        return BadRequestError(message, status)
    if status >= 500:
        return ServiceUnavailableError(message, status)
    return LLMError(message, status)


async def chat(
    *, base_url: str, api_key: str, model: str, messages: list[dict[str, str]], temperature: float = 0,
    max_tokens: int = 0, json_mode: bool = False, ca_bundle: str = "",
    on_delta: Callable[[str], None] | None = None, timeout: float | None = None, stream: bool = False,
    extra: dict[str, Any] | None = None, on_reasoning: Callable[[str], None] | None = None,
) -> tuple[str, str | None]:
    """Envoie une conversation ; renvoie (texte, finish_reason). Avec on_delta, réponse reçue en streaming.

    timeout : attente maximale sans rien recevoir (secondes) ; par défaut 600 s pour une réponse complète et
    STREAM_READ_TIMEOUT entre deux morceaux en streaming.
    stream : réponse reçue au fil de l'eau même sans on_delta (le délai porte alors sur chaque morceau).
    extra : champs ajoutés tels quels à la requête (ex. {"reasoning_effort": "none"} pour Ollama).
    on_reasoning : reçoit la réflexion accumulée d'un modèle qui « réfléchit » (champ « reasoning » d'Ollama,
    « reasoning_content » de vLLM ou DeepSeek), qui n'arrive pas dans la réponse elle-même.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    payload.update(extra or {})
    for _ in range(3):
        try:
            return await _send(_client(ca_bundle), url, headers, payload, on_delta, timeout, stream, on_reasoning)
        except BadRequestError as exc:
            lowered = str(exc).lower()
            # Certains serveurs (anciennes versions de vLLM…) refusent response_format : la consigne impose déjà le JSON.
            if "response_format" in payload and any(k in lowered for k in ("response_format", "json_object", "json mode")):
                payload.pop("response_format")
            # Champ de réflexion inconnu d'un serveur : la requête repart sans lui.
            elif "reasoning_effort" in payload and any(k in lowered for k in ("reasoning_effort", "reasoning effort")):
                payload.pop("reasoning_effort")
            else:
                raise
    return await _send(_client(ca_bundle), url, headers, payload, on_delta, timeout, stream, on_reasoning)


async def _send(client: httpx.AsyncClient, url: str, headers: dict[str, str], payload: dict[str, Any],
                on_delta: Callable[[str], None] | None, timeout: float | None = None,
                stream: bool = False, on_reasoning: Callable[[str], None] | None = None) -> tuple[str, str | None]:
    try:
        if on_delta is None and not stream:
            kwargs = {"timeout": httpx.Timeout(timeout, connect=20.0)} if timeout else {}
            resp = await client.post(url, headers=headers, json=payload, **kwargs)
            if resp.status_code >= 400:
                raise _error(resp.status_code, resp.text)
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            return (choice.get("message") or {}).get("content") or "", choice.get("finish_reason")

        payload = {**payload, "stream": True}
        text, thought, finish = [], [], None
        # En streaming, le délai porte sur chaque morceau : un modèle bloqué est détecté en 3 minutes.
        stream_timeout = httpx.Timeout(timeout or STREAM_READ_TIMEOUT, connect=20.0)
        async with client.stream("POST", url, headers=headers, json=payload, timeout=stream_timeout) as resp:
            if resp.status_code >= 400:
                raise _error(resp.status_code, (await resp.aread()).decode("utf-8", "replace"))
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    event = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("error"):
                    raise _error(500, chunk)
                for choice in event.get("choices") or []:
                    step = choice.get("delta") or {}
                    reasoning = step.get("reasoning") or step.get("reasoning_content") or ""
                    if isinstance(reasoning, str) and reasoning:
                        thought.append(reasoning)
                        if on_reasoning:
                            on_reasoning("".join(thought))
                    delta = step.get("content") or ""
                    if delta:
                        text.append(delta)
                        if on_delta:
                            on_delta("".join(text))
                    finish = choice.get("finish_reason") or finish
        return "".join(text), finish
    except httpx.TimeoutException as exc:
        raise TimeoutError(f"délai dépassé ({exc.__class__.__name__})") from exc
    except httpx.ConnectError as exc:
        raise ConnectionFailedError(f"connexion impossible à {url} : {exc}") from exc
    except httpx.HTTPError as exc:
        raise ServiceUnavailableError(f"erreur réseau : {exc}") from exc


async def ollama_context_length(base_url: str, model: str, ca_bundle: str = "") -> int | None:
    """Fenêtre réellement ouverte par Ollama pour un modèle chargé (GET /api/ps), ou None si inconnue.

    Par son adresse compatible OpenAI, Ollama ne prend pas la taille de contexte demandée : il garde la sienne
    (souvent quelques milliers de tokens) et coupe sans prévenir ce qui dépasse.
    """
    root = base_url.rstrip("/")
    root = root[: -len("/v1")] if root.endswith("/v1") else root
    wanted = model if ":" in model else f"{model}:latest"
    try:
        resp = await _client(ca_bundle).get(f"{root}/api/ps", timeout=httpx.Timeout(5.0))
        entries = resp.json().get("models") or [] if resp.status_code == 200 else []
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    for entry in entries:
        if isinstance(entry, dict) and wanted in (entry.get("name"), entry.get("model")):
            try:
                return int(entry.get("context_length") or 0) or None
            except (TypeError, ValueError):
                return None
    return None
