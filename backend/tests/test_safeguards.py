"""Garde-fous de fidélité, sans appel au modèle."""
import pytest

from app.services import analysis_service as svc
from app.services.batch_pipeline import Item, uncovered
from app.services.source_lookup import passage, resolve
from tests.fixtures.expected import FACTS, QUOTES


@pytest.fixture
def compte_rendu(fixtures_dir):
    return svc.store_document((fixtures_dir / "compte_rendu_6_sujets.txt").read_bytes(), "compte_rendu_6_sujets.txt")


# -- Verbatims ------------------------------------------------------------------

@pytest.mark.parametrize("quote, expected", [
    ("Je ne savais plus lequel ouvrir en premier.", "exact"),
    ("je ne savais plus lequel ouvrir en premier", "exact"),  # casse et ponctuation ignorées
    ("Je ne savais plus quel mail ouvrir en premier.", "close"),
    ("Je passe plus de temps à remplir les outils qu'à parler aux clients.", "close"),
    ("Les clients se sentent perdus dès le premier jour et abandonnent.", "absent"),
    ("", ""),
])
def test_verification_des_verbatims(compte_rendu, quote, expected):
    assert svc.QuoteChecker(compte_rendu.plain_text()).check(quote) == expected


# -- Sources ----------------------------------------------------------------------

@pytest.mark.parametrize("location, refs", [
    ("L4", ["L4"]),
    ("Lignes 18 à 19", ["L18", "L19"]),
    ("ligne 18", ["L18"]),
])
def test_resolution_des_reperes(compte_rendu, location, refs):
    from app.services.source_lookup import doc_lines

    lines = doc_lines(compte_rendu)
    assert [lines[i].ref for i in resolve(compte_rendu, location)] == refs


def test_repere_introuvable_propose_le_passage_le_plus_proche(compte_rendu):
    r = passage(compte_rendu, "L999", "Je dois demander à mon fils de signer à ma place.")
    assert r["found"] is False and r["nearest"] is True
    assert [l["ref"] for l in r["lines"] if l["hit"]] == ["L19"]


# -- Contrôle de couverture (analyse par lots) -------------------------------------

def test_chiffre_absent_detecte_meme_s_il_apparait_dans_un_autre_nombre():
    items = [Item("e1", "chiffre", "La double saisie coûte 20 minutes par rendez-vous.", "a.txt", "L20")]
    data = {"themes": [{"summary": "Relevés de 2023 ; 120 appels.", "points": [{"sources": [{"location": "L20"}]}]}]}
    assert [i.id for i in uncovered(items, data)] == ["e1"]
    data["themes"][0]["summary"] += " La double saisie prend 20 minutes."
    assert uncovered(items, data) == []


def test_nom_propre_absent_detecte():
    items = [Item("e1", "fait", "Le samedi, seule l'agence de Lorient est ouverte.", "a.txt", "L9")]
    assert uncovered(items, {"brief": "Les agences ferment tôt."}) == items


# -- Graphe de flux -----------------------------------------------------------------

def test_graphe_de_flux_nettoye_et_echappe():
    g = svc.normalize_flow({
        "nodes": [
            {"id": "a", "label": "Entrée", "type": "entry"},
            {"id": "b", "label": 'Client existant ? <script> "x" | y', "type": "decision"},
            {"id": "c", "label": "Abandon", "type": "exit"},
            {"id": "a", "label": "doublon", "type": "step"},
        ],
        "edges": [
            {"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "Non | session"},
            {"from": "b", "to": "b"}, {"from": "b", "to": "zz"}, {"from": "a", "to": "b"},
        ],
    })
    assert len(g["nodes"]) == 3 and len(g["edges"]) == 2
    assert g["edges"][1]["kind"] == "exit"  # vers un nœud de sortie
    assert "<script>" not in g["mermaid"] and "#lt;script#gt;" in g["mermaid"]
    assert "#124;" in g["mermaid"]


def test_ancien_format_lineaire_converti_en_graphe():
    g = svc.normalize_flow([{"label": "Entrée", "kind": "entry"}, {"label": "Formulaire", "exit": "Abandon"}])
    assert [n["type"] for n in g["nodes"]] == ["entry", "step", "exit"]


# -- Aperçu des thèmes pendant le streaming ----------------------------------------------

def test_apercu_des_themes_pendant_le_streaming():
    partial = '{"title": "Étude", "themes": [{"title": "Suivi", "points": []}, {"title": "Accessibil'
    assert svc._streamed_names(partial, "global") == ("Étude", ["Suivi"])
    full = partial + 'ité"}], "actions": [{"title": "Pas un thème"}]}'
    assert svc._streamed_names(full, "global")[1] == ["Suivi", "Accessibilité"]


def test_apercu_des_etapes_en_mode_flux():
    text = '{"title": "P", "phases": [{"name": "A"}, {"name": "B"}], "priorities": [{"title": "pas une étape"}]}'
    assert svc._streamed_names(text, "flow")[1] == ["A", "B"]


def test_les_verbatims_de_reference_existent(fixtures_dir):
    """Sécurité des données de test : chaque verbatim attendu figure bien dans les documents."""
    text = "\n".join((fixtures_dir / name).read_text(encoding="utf-8") for name in FACTS)
    checker = svc.QuoteChecker(text)
    assert all(checker.check(q) == "exact" for q in QUOTES)


def test_nombre_verifie_avec_le_mot_qui_le_suit():
    """« 6 » apparaît presque toujours ailleurs : c'est « 6 participants » qu'il faut retrouver."""
    items = [Item("e1", "fait", "6 participants ont désactivé toutes les alertes.", "a.txt", "L1")]
    assert uncovered(items, {"brief": "Les alertes se mélangent ; 6 sujets ont été abordés."}) == items
    assert uncovered(items, {"brief": "Au total, 6 participants les ont coupées."}) == []
