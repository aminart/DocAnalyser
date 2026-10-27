"""Client compatible OpenAI (httpx) : réponses, streaming, erreurs typées, repli sans response_format."""
import asyncio
import json

import httpx
import pytest

from app.services import llm_client


def _install(monkeypatch, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(llm_client, "_CLIENTS", {"default": client})


def _chat(**kw):
    args = {"base_url": "https://llm.test/v1", "api_key": "k", "model": "m",
            "messages": [{"role": "user", "content": "x"}], **kw}
    return asyncio.run(llm_client.chat(**args))


def test_reponse_complete_et_requete_conforme(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers["Authorization"], body=json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": 1}'}, "finish_reason": "stop"}]})

    _install(monkeypatch, handler)
    assert _chat(json_mode=True, max_tokens=500) == ('{"ok": 1}', "stop")
    assert seen["url"] == "https://llm.test/v1/chat/completions" and seen["auth"] == "Bearer k"
    assert seen["body"]["response_format"] == {"type": "json_object"} and seen["body"]["max_tokens"] == 500


def test_streaming_texte_accumule(monkeypatch):
    events = [{"choices": [{"delta": {"content": "Bon"}}]}, {"choices": [{"delta": {"content": "jour"}, "finish_reason": "length"}]}]
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    _install(monkeypatch, lambda r: httpx.Response(200, text=body, headers={"content-type": "text/event-stream"}))
    seen = []
    assert _chat(on_delta=seen.append) == ("Bonjour", "length")
    assert seen == ["Bon", "Bonjour"]


@pytest.mark.parametrize("status, body, cls", [
    (429, {"error": {"message": "Quota exceeded per day"}}, llm_client.RateLimitError),
    (503, {"error": {"message": "overloaded"}}, llm_client.ServiceUnavailableError),
    (401, {"error": {"message": "bad key"}}, llm_client.AuthenticationError),
    (404, {"error": {"message": "model not found"}}, llm_client.NotFoundError),
    (400, {"error": {"message": "prompt is too long: maximum context"}}, llm_client.ContextWindowExceededError),
    (400, [{"error": {"message": "invalid argument"}}], llm_client.BadRequestError),
])
def test_erreurs_typees(monkeypatch, status, body, cls):
    _install(monkeypatch, lambda r: httpx.Response(status, json=body))
    with pytest.raises(cls) as exc:
        _chat()
    assert exc.value.status == status


def test_serveur_sans_response_format_reessaye_sans(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        if "response_format" in bodies[-1]:
            return httpx.Response(400, json={"error": {"message": "response_format is not supported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    _install(monkeypatch, handler)
    assert _chat(json_mode=True) == ("{}", "stop")
    assert len(bodies) == 2 and "response_format" not in bodies[1]


def test_connexion_impossible(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    _install(monkeypatch, handler)
    with pytest.raises(llm_client.ServiceUnavailableError):
        _chat()
