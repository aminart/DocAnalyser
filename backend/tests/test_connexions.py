"""Écran Réglages : plusieurs connexions aux modèles, clé jamais renvoyée, .env en lecture seule, certificat,
test de connexion avec diagnostic (faux serveurs HTTP et HTTPS avec autorité interne)."""
import base64
import datetime as dt
import ipaddress
import json
import shutil
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from app.core import connexions
from app.main import app
from app.services import analysis_service as svc


@pytest.fixture(autouse=True)
def vide():
    shutil.rmtree(connexions.dossier_config(), ignore_errors=True)
    yield
    shutil.rmtree(connexions.dossier_config(), ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app)


def creer(client, **champs):
    corps = {"kind": "openai", "name": "Passerelle interne", "api_base": "https://passerelle.interne/v1",
             "api_key": "sk-passerelle-1234567890ABCD", "models": ["mistral-large", "mistral-small"]} | champs
    r = client.post("/api/v2/connections", json=corps)
    assert r.status_code == 200, r.text
    return r.json()


def test_ajouter_une_connexion_sans_jamais_renvoyer_la_cle(client):
    r = creer(client)
    c = next(c for c in r["connections"] if c["id"] == r["created"])
    assert c["source"] == "app" and c["has_api_key"] and c["api_key_hint"] == "ABCD"
    assert "sk-passerelle" not in json.dumps(r) and "sk-passerelle" not in json.dumps(client.get("/api/v2/connections").json())
    assert "sk-passerelle" not in (connexions.dossier_config() / "connexions.json").read_text(encoding="utf-8")
    # Ses modèles sont proposés pour une analyse, avec le nom de la connexion
    modeles = {m["id"]: m for m in client.get("/api/v2/models").json()}
    assert {f"{c['id']}:mistral-large", f"{c['id']}:mistral-small"} <= set(modeles)
    m = modeles[f"{c['id']}:mistral-large"]
    assert m["provider_label"] == "Passerelle interne" and m["configured"] and m["tier"] == "deep"
    spec = svc.get_model(f"{c['id']}:mistral-small")
    assert spec.provider.api_key == "sk-passerelle-1234567890ABCD" and spec.provider.api_base == "https://passerelle.interne/v1"


def test_plusieurs_connexions_et_types(client):
    creer(client)
    creer(client, kind="gemini", name="", api_base="", api_key="cle-gemini-12345678", models=["gemini-2.5-flash"])
    creer(client, kind="anthropic", name="Claude test", api_base="", api_key=None, models=["claude-sonnet-4-5"])
    r = client.get("/api/v2/connections").json()["connections"]
    assert [c["name"] for c in r] == ["Passerelle interne", "Google Gemini", "Claude test"]
    gemini = next(c for c in r if c["kind"] == "gemini")
    assert gemini["api_base"].startswith("https://generativelanguage.googleapis.com") and gemini["context_tokens"] == 1_000_000
    modeles = {m["name"]: m for m in client.get("/api/v2/models").json()}
    assert modeles["gemini-2.5-flash"]["configured"] is True
    assert modeles["claude-sonnet-4-5"]["configured"] is False  # Claude exige une clé


def test_cle_gardee_ou_effacee_et_suppression(client):
    id_ = creer(client)["created"]
    corps = {"kind": "openai", "name": "Renommée", "api_base": "http://localhost:11434/v1", "models": ["llama3"]}
    client.put(f"/api/v2/connections/{id_}", json=corps | {"api_key": None})
    c = connexions.trouver(id_)
    assert connexions.cle(c) == "sk-passerelle-1234567890ABCD" and c.name == "Renommée" and c.models == ["llama3"]
    client.put(f"/api/v2/connections/{id_}", json=corps | {"api_key": ""})
    assert connexions.cle(connexions.trouver(id_)) == ""
    assert client.delete(f"/api/v2/connections/{id_}").json()["connections"] == []
    assert not any(m["id"].startswith(id_) for m in client.get("/api/v2/models").json())


def test_url_obligatoire_pour_une_passerelle(client):
    r = client.post("/api/v2/connections", json={"kind": "openai", "name": "x", "api_base": "passerelle", "models": []})
    assert r.status_code == 422


def test_env_affiche_en_lecture_seule(client, monkeypatch):
    monkeypatch.setattr(svc.settings, "CUSTOM_LLM_API_BASE", "https://depuis-le-env.interne/v1")
    monkeypatch.setattr(svc.settings, "CUSTOM_LLM_API_KEY", "cle-du-env-ABCDEFGH")
    monkeypatch.setattr(svc.settings, "CUSTOM_LLM_AVAILABLE_MODELS", "modele-env")
    creer(client)
    r = client.get("/api/v2/connections").json()["connections"]
    env = r[0]
    assert env["source"] == "env" and env["env_prefix"] == "CUSTOM_LLM" and env["api_key_hint"] == "EFGH"
    assert env["models"] == ["modele-env"] and "cle-du-env" not in json.dumps(r)
    assert len(r) == 2


# --- Certificats -----------------------------------------------------------------------------------------

def _autorite():
    cle = ec.generate_private_key(ec.SECP256R1())
    nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Autorite interne test")])
    maintenant = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nom).issuer_name(nom).public_key(cle.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(maintenant - dt.timedelta(days=1))
            .not_valid_after(maintenant + dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(cle, hashes.SHA256()))
    return cle, cert


def _certificat_serveur(cle_ca, ca):
    cle = ec.generate_private_key(ec.SECP256R1())
    maintenant = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
            .issuer_name(ca.subject).public_key(cle.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(maintenant - dt.timedelta(days=1)).not_valid_after(maintenant + dt.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(cle_ca, hashes.SHA256()))
    return cle, cert


def test_certificat_importe(client):
    _, ca = _autorite()
    id_ = creer(client)["created"]
    r = client.post(f"/api/v2/connections/{id_}/certificate",
                    files={"file": ("autorite.crt", ca.public_bytes(serialization.Encoding.PEM))})
    assert r.status_code == 200
    c = next(c for c in r.json()["connections"] if c["id"] == id_)
    assert c["certificate"]["name"] == "autorite.crt" and c["certificate"]["expires_at"]
    assert svc.get_model(f"{id_}:mistral-large").provider.ca_bundle == str(connexions.chemin_certificat(id_))
    assert client.post(f"/api/v2/connections/{id_}/certificate", files={"file": ("x.crt", b"faux")}).status_code == 422
    r = client.delete(f"/api/v2/connections/{id_}/certificate").json()
    assert next(c for c in r["connections"] if c["id"] == id_)["certificate"] is None


# --- Test de connexion -----------------------------------------------------------------------------------

def _serveur(liste=True, https=None):
    recus = []

    class S(BaseHTTPRequestHandler):
        def do_GET(self):
            recus.append(("GET", self.path, self.headers.get("Authorization")))
            if not liste:
                return self._json(404, {"error": {"message": "not found"}})
            self._json(200, {"data": [{"id": "mistral-small:latest"}, {"id": "llama3:8b"}]})

        def do_POST(self):
            corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            recus.append(("POST", self.path, self.headers.get("Authorization")))
            if self.headers.get("Authorization") == "Bearer mauvaise":
                return self._json(401, {"error": {"message": "invalid key"}})
            self._json(200, {"choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}], "model": corps["model"]})

        def _json(self, code, data):
            brut = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(brut)))
            self.end_headers()
            self.wfile.write(brut)

        def log_message(self, *a):
            pass

    serveur = HTTPServer(("127.0.0.1", 0), S)
    if https:
        contexte = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexte.load_cert_chain(*https)
        serveur.socket = contexte.wrap_socket(serveur.socket, server_side=True)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    return serveur, recus


def test_modeles_listes_par_le_serveur(client):
    serveur, _ = _serveur()
    base = f"http://127.0.0.1:{serveur.server_port}/v1"
    try:
        ok = client.post("/api/v2/connections/test", json={"api_base": base, "models": ["mistral-small", "qwen"]}).json()
        assert ok["ok"] and ok["available"] == ["llama3:8b", "mistral-small:latest"] and ok["missing"] == ["qwen"]
        ko = client.post("/api/v2/connections/test", json={"api_base": base, "models": ["qwen"]}).json()
        assert not ko["ok"] and ko["field"] == "models" and ko["available"]
    finally:
        serveur.shutdown()


def test_passerelle_sans_liste_de_modeles(client):
    serveur, recus = _serveur(liste=False)
    base = f"http://127.0.0.1:{serveur.server_port}/v1"
    try:
        ok = client.post("/api/v2/connections/test", json={"api_base": base, "api_key": "bonne", "models": ["m"]}).json()
        assert ok["ok"] and recus[-1][:2] == ("POST", "/v1/chat/completions")
        ko = client.post("/api/v2/connections/test", json={"api_base": base, "api_key": "mauvaise", "models": ["m"]}).json()
        assert not ko["ok"] and ko["field"] == "api_key"
    finally:
        serveur.shutdown()


def test_serveur_injoignable(client):
    r = client.post("/api/v2/connections/test", json={"api_base": "http://127.0.0.1:9/v1", "models": ["m"]}).json()
    assert not r["ok"] and r["field"] == "api_base" and "injoignable" in r["title"]


def test_cle_enregistree_utilisee_et_resultat_garde(client):
    serveur, recus = _serveur()
    base = f"http://127.0.0.1:{serveur.server_port}/v1"
    try:
        id_ = creer(client, api_base=base, api_key="cle-enregistree-1234", models=["mistral-small"])["created"]
        r = client.post("/api/v2/connections/test", json={"id": id_, "api_base": base, "api_key": None, "models": ["mistral-small"]}).json()
        assert r["ok"] and recus[-1][2] == "Bearer cle-enregistree-1234"
        assert connexions.trouver(id_).last_test["ok"] is True
    finally:
        serveur.shutdown()


def test_https_autorite_interne(client, tmp_path):
    cle_ca, ca = _autorite()
    cle_srv, cert_srv = _certificat_serveur(cle_ca, ca)
    (tmp_path / "srv.pem").write_bytes(cert_srv.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "srv.key").write_bytes(cle_srv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                              serialization.NoEncryption()))
    serveur, _ = _serveur(https=(tmp_path / "srv.pem", tmp_path / "srv.key"))
    base = f"https://localhost:{serveur.server_port}/v1"
    pem = ca.public_bytes(serialization.Encoding.PEM)
    try:
        sans = client.post("/api/v2/connections/test", json={"api_base": base, "models": ["mistral-small"]}).json()
        assert not sans["ok"] and sans["field"] == "certificate"
        # Certificat choisi dans le formulaire, pas encore enregistré
        avec = client.post("/api/v2/connections/test", json={"api_base": base, "models": ["mistral-small"],
                                                             "certificate_b64": base64.b64encode(pem).decode()}).json()
        assert avec["ok"], avec
        # Puis enregistré avec la connexion
        id_ = creer(client, api_base=base, models=["mistral-small"])["created"]
        client.post(f"/api/v2/connections/{id_}/certificate", files={"file": ("autorite.crt", pem)})
        assert client.post("/api/v2/connections/test", json={"id": id_, "api_base": base, "models": ["mistral-small"]}).json()["ok"]
    finally:
        serveur.shutdown()


def test_gemini_sans_cle(client):
    r = client.post("/api/v2/connections/test", json={"kind": "gemini", "models": ["gemini-2.5-flash"]}).json()
    assert not r["ok"] and r["field"] == "api_key"
