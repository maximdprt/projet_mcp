"""Interface web du CRM : un test par endpoint nouveau ou modifié, et les garde-fous de la page.

L'interface ne décide rien : elle affiche ce que le MCP a enregistré et ce que le CRM autorise
(`actions_possibles`). Le serveur revérifie chaque action (403 pour la clé du MCP, 409 selon le statut).
"""

import asyncio
import re

import httpx
import pytest

from crm import app as crm_app
from demo.harnais import base_temporaire, clients
from verif_fournisseur import verifications as v

ORDRE_CONTROLES = ["identifiants", "identite_entreprise", "nom_facture", "procedures_bodacc", "gel_des_avoirs",
                   "tva_vies", "adresse_facture", "montant_eur", "referentiel_crm"]


@pytest.fixture(autouse=True)
def crm_neuf():
    base_temporaire()


def requete(methode, chemin, cle=None, **kw):
    async def _run():
        entetes = {"X-API-Key": cle} if cle else {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=crm_app.app), base_url="http://crm",
                                     headers=entetes) as c:
            return await c.request(methode, chemin, **kw)
    return asyncio.run(_run())


def admin(methode, chemin, **kw):
    return requete(methode, chemin, crm_app.CLE_ADMIN, **kw)


def mcp(methode, chemin, **kw):
    return requete(methode, chemin, crm_app.CLE_MCP, **kw)


def traiter(facture_id):
    async def _run():
        async with clients() as (ext, crm):
            return await v.traiter_factures_crm(ext, crm, facture_id)
    return asyncio.run(_run())


# ------------------------------------------------------------------ GET /  et  /interface/*

def test_la_racine_ouvre_la_presentation():
    r = requete("GET", "/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/diapos/"


def test_page_servie_sans_cle_et_protegee_par_une_csp():
    r = requete("GET", "/crm")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "<script src=\"/interface/app.js" in r.text
    assert "<script>" not in r.text                    # aucun script en ligne
    assert "16 factures" not in r.text and "F01" not in r.text   # aucune donnée sans clé


@pytest.mark.parametrize("fichier", ["index.html", "app.js", "style.css"])
def test_aucune_cle_ecrite_dans_l_interface(fichier):
    r = requete("GET", f"/interface/{fichier}")
    assert r.status_code == 200
    for cle in (crm_app.CLE_ADMIN, crm_app.CLE_MCP, "cle-admin-demo-a-changer", "cle-mcp-demo-a-changer"):
        assert cle not in r.text


def test_le_javascript_n_interprete_jamais_de_html_ni_de_float():
    js = requete("GET", "/interface/app.js").text
    assert not re.search(r"\.innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", js)
    assert not re.search(r"parseFloat|Number\(\s*f\.montant|toFixed", js)
    assert "localStorage" not in js                    # la clé ne survit pas à la fermeture de l'onglet


# ------------------------------------------------------------------ GET /api/session

def test_session_indique_le_role_de_la_cle():
    mode = crm_app.MODE_PRESENTATION
    assert admin("GET", "/api/session").json() == {"role": "admin", "peut_agir": True, "presentation": mode}
    assert mcp("GET", "/api/session").json() == {"role": "mcp", "peut_agir": False, "presentation": mode}
    assert requete("GET", "/api/session").status_code == 401
    assert requete("GET", "/api/session", "mauvaise-cle").status_code == 401


# ------------------------------------------------------------------ GET /api/scenarios  et  GET /api/journal?depuis=

def test_scenarios_decrivent_les_16_pieges_et_le_resultat_attendu():
    from crm.donnees_demo import SCENARIOS
    s = admin("GET", "/api/scenarios").json()
    assert [x["facture_id"] for x in s] == [f["id"] for f, *_ in SCENARIOS]
    assert all(x["titre"] and x["piege"] and x["statut_attendu"] in
               {"verifiee", "bloquee", "a_verifier_humain"} for x in s)
    f15 = next(x for x in s if x["facture_id"] == "F15")
    assert f15["titre"] == "Injection de prompt" and "objet" in f15["champs_pieges"]
    factures = {f["id"]: f for f in admin("GET", "/api/factures").json()}
    for x in s:                                   # chaque champ signalé existe bien sur la facture
        assert all(champ in factures[x["facture_id"]] for champ in x["champs_pieges"])
    assert mcp("GET", "/api/scenarios").status_code == 200
    assert requete("GET", "/api/scenarios").status_code == 401


def test_journal_depuis_ne_renvoie_que_les_nouvelles_entrees():
    tout = admin("GET", "/api/journal").json()
    dernier = tout[-1]["id"]
    assert admin("GET", "/api/journal", params={"depuis": dernier}).json() == []
    traiter("F02")
    traiter("F09")
    nouvelles = admin("GET", "/api/journal", params={"depuis": dernier}).json()
    assert [(e["facture_id"], e["action"]) for e in nouvelles] == [("F02", "verification"), ("F09", "verification")]
    seulement_f09 = admin("GET", "/api/journal", params={"depuis": dernier, "facture_id": "F09"}).json()
    assert [e["facture_id"] for e in seulement_f09] == ["F09"]


def test_le_scenario_attendu_correspond_au_verdict_du_mcp():
    """Ce que le moniteur affiche comme « conforme » : le verdict écrit par le MCP = le statut attendu."""
    async def _run():
        async with clients() as (ext, crm):
            return await v.traiter_factures_crm(ext, crm)
    asyncio.run(_run())
    attendus = {x["facture_id"]: x["statut_attendu"] for x in admin("GET", "/api/scenarios").json()}
    verdicts = {e["facture_id"]: e["statut"] for e in admin("GET", "/api/journal").json() if e["action"] == "verification"}
    assert verdicts == attendus


# ------------------------------------------------------------------ GET /api/synthese

def test_synthese_compte_les_statuts_et_le_montant_retenu_en_decimal():
    s = admin("GET", "/api/synthese").json()
    assert s["par_statut"]["recue"] == 16 and s["montant_retenu_eur"] == "0.00"
    for scenario in ("F01", "F02", "F09", "F12"):
        traiter(scenario)
    s = admin("GET", "/api/synthese").json()
    factures = {f["id"]: f for f in admin("GET", "/api/factures").json()}
    from decimal import Decimal
    attendu = Decimal(factures["F02"]["montant"]) + Decimal(factures["F09"]["montant"])   # bloquée + à vérifier
    assert s["montant_retenu_eur"] == str(attendu.quantize(Decimal("0.01")))
    assert s["par_statut"]["verifiee"] == 2 and s["montants_non_convertis"] == 0
    assert re.fullmatch(r"\d+\.\d{2}", s["montant_paye_eur"])                            # chaîne, pas un float
    assert requete("GET", "/api/synthese").status_code == 401


def test_synthese_lot_complet_tout_l_argent_douteux_est_retenu():
    async def _run():
        async with clients() as (ext, crm):
            return await v.traiter_factures_crm(ext, crm)
    asyncio.run(_run())
    s = admin("GET", "/api/synthese").json()
    assert s["par_statut"].get("verifiee") == 2
    assert s["par_statut"]["bloquee"] == 9 and s["par_statut"]["a_verifier_humain"] == 5
    assert s["montant_retenu_eur"] == "112680.00"            # le chiffre de RAPPORT_DEMO.md


# ------------------------------------------------------------------ POST /api/factures/{id}/verification (controles)

def test_le_detail_contient_les_controles_du_mcp_dans_l_ordre():
    traiter("F02")
    f = admin("GET", "/api/factures/F02").json()
    v_ = f["derniere_verification"]
    assert [c["controle"] for c in v_["controles"]] == ORDRE_CONTROLES
    assert all(c["source"] and c["resultat"] in {"OK", "ALERTE", "INDISPONIBLE", "NON_DEMANDE"}
               for c in v_["controles"])
    referentiel = next(c for c in v_["controles"] if c["controle"] == "referentiel_crm")
    assert referentiel["resultat"] == "ALERTE"
    assert "IBAN_DIFFERENT_DU_REFERENTIEL" in {a["code"] for a in v_["alertes"]}


def test_le_crm_ne_garde_que_le_resume_des_controles():
    traiter("F01")
    for c in admin("GET", "/api/factures/F01").json()["derniere_verification"]["controles"]:
        assert set(c) <= {"controle", "source", "resultat", "raison"}     # jamais le détail des sources


def test_une_panne_apparait_comme_indisponible_dans_le_detail():
    from conftest import RE, FausseAPI
    api = FausseAPI()
    api.pannes = {RE: 500}

    async def _run():
        async with clients(api.transport()) as (ext, crm):
            return await v.traiter_factures_crm(ext, crm, "F01")
    asyncio.run(_run())
    f = admin("GET", "/api/factures/F01").json()
    identite = next(c for c in f["derniere_verification"]["controles"] if c["controle"] == "identite_entreprise")
    assert identite["resultat"] == "INDISPONIBLE" and identite["raison"]
    assert f["statut"] == "impossible_de_verifier" and f["actions_possibles"]["payer"] is False


def test_un_resultat_de_controle_inconnu_est_refuse():
    corps = {"statut": "verifiee", "statut_mcp": "AUCUNE_ALERTE_DETECTEE", "empreinte": "0" * 64,
             "controles": [{"controle": "identifiants", "source": "calcul local", "resultat": "PAYE"}]}
    assert mcp("POST", "/api/factures/F01/verification", json=corps).status_code == 422
    assert admin("GET", "/api/factures/F01").json()["statut"] == "recue"


# ------------------------------------------------------------------ GET /api/factures(/{id}) : actions_possibles

def test_actions_possibles_suivent_le_statut():
    def actions(fid):
        return admin("GET", f"/api/factures/{fid}").json()["actions_possibles"]

    assert actions("F01") == {"payer": False, "valider": False}     # reçue
    traiter("F01")
    assert actions("F01") == {"payer": True, "valider": False}      # vérifiée
    traiter("F09")
    assert actions("F09") == {"payer": False, "valider": True}      # à vérifier par un humain
    traiter("F02")
    assert actions("F02") == {"payer": False, "valider": False}     # bloquée
    assert all("actions_possibles" in f for f in admin("GET", "/api/factures").json())


def test_actions_possibles_n_ouvrent_aucun_droit_au_mcp():
    traiter("F01")
    assert mcp("GET", "/api/factures/F01").json()["actions_possibles"]["payer"] is True
    assert mcp("POST", "/api/factures/F01/paiement").status_code == 403


# ------------------------------------------------------------------ boutons de l'interface (endpoints existants)

def test_validation_humaine_exige_un_commentaire():
    traiter("F09")
    for corps in ({"valideur": "Directrice financière"},
                  {"valideur": "Directrice financière", "commentaire": "ok"}):
        assert admin("POST", "/api/factures/F09/validation-humaine", json=corps).status_code == 422
    assert admin("GET", "/api/factures/F09").json()["statut"] == "a_verifier_humain"


def test_bouton_payer_refuse_par_le_serveur_meme_si_l_interface_est_contournee():
    traiter("F02")
    r = admin("POST", "/api/factures/F02/paiement")
    assert r.status_code == 409 and "verifiee" in r.json()["detail"]


def test_parcours_complet_de_l_interface_validation_paiement_journal():
    traiter("F09")
    assert admin("POST", "/api/factures/F09/validation-humaine",
                 json={"valideur": "Directrice financière", "commentaire": "Contre-appel fait, commande confirmée."}
                 ).status_code == 200
    assert admin("POST", "/api/factures/F09/paiement").status_code == 200
    journal = admin("GET", "/api/journal", params={"facture_id": "F09"}).json()
    assert [j["action"] for j in journal] == ["verification", "validation_humaine", "paiement_simule"]
    assert admin("GET", "/api/factures/F09").json()["actions_possibles"] == {"payer": False, "valider": False}


def test_reinitialiser_la_demo_reservee_a_l_administrateur():
    traiter("F01")
    assert mcp("POST", "/api/demo/reinitialiser").status_code == 403
    assert admin("GET", "/api/factures/F01").json()["statut"] == "verifiee"
    assert admin("POST", "/api/demo/reinitialiser").json()["reinitialise"] is True
    assert admin("GET", "/api/factures/F01").json()["statut"] == "recue"
    assert {f["statut"] for f in admin("GET", "/api/factures").json() if f["id"].startswith("F")} == {"recue"}
