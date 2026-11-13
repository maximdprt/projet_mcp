"""Le SaaS de bout en bout : on dépose une facture, le MCP l'analyse, le verdict revient avec ses raisons.

L'appel au serveur MCP (sous-processus stdio) est remplacé par un appel en mémoire au même outil
`traiter_factures_crm` : mêmes règles, même écriture dans le CRM, sans réseau ni processus.
"""

import asyncio
import json

import httpx
import pytest

from crm import analyse, db
from crm import app as crm_app
from crm.donnees_demo import SCENARIOS
from crm.pdf_factures import facture_pdf
from demo.harnais import base_temporaire, clients
from verif_fournisseur import verifications as v


async def executeur_memoire(arguments: dict) -> dict:
    async with clients() as (ext, crm):
        return await v.traiter_factures_crm(ext, crm, arguments.get("facture_id"))


@pytest.fixture(autouse=True)
def saas_vide():
    base_temporaire()
    db.initialiser(db.CHEMIN, jeu_de_test=False)      # boîte de réception vide, comme le SaaS au démarrage
    avant = analyse.executeur
    analyse.executeur = executeur_memoire
    yield
    analyse.executeur = avant


def requete(methode, chemin, cle=None, **kw):
    async def _run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=crm_app.app), base_url="http://crm",
                                     headers={"X-API-Key": cle} if cle else {}) as c:
            return await c.request(methode, chemin, **kw)
    return asyncio.run(_run())


def admin(methode, chemin, **kw):
    return requete(methode, chemin, crm_app.CLE_ADMIN, **kw)


def deposer(nom, contenu, type_mime="application/pdf"):
    return admin("POST", "/api/factures/depot", files={"fichier": (nom, contenu, type_mime)})


def deposer_et_creer(facture):
    lu = deposer(f"{facture['id']}.pdf", facture_pdf(facture)).json()
    corps = {k: val for k, val in lu["champs"].items() if val is not None}
    corps.update(nom_fichier=lu["fichier"]["nom"], empreinte_fichier=lu["fichier"]["empreinte"])
    r = admin("POST", "/api/factures", json=corps)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ dépôt et lecture

@pytest.mark.parametrize("facture", [s[0] for s in SCENARIOS], ids=[s[0]["id"] for s in SCENARIOS])
def test_le_pdf_depose_est_relu_sans_erreur(facture):
    r = deposer("facture.pdf", facture_pdf(facture))
    assert r.status_code == 200
    lu = r.json()
    assert lu["manquants"] == []
    c = lu["champs"]
    assert c["numero"] == facture["numero"] and c["montant"] == facture["montant"] and c["devise"] == facture["devise"]
    assert c["siret"] == facture["siret"] and c["iban"] == facture["iban"] and c["nom_emetteur"] == facture["nom_emetteur"]
    assert len(lu["fichier"]["empreinte"]) == 64


def test_depot_json_et_texte():
    j = {"numero": "X-1", "fournisseur": "ATELIER MERCIER", "siret": "901 234 567 00013", "montant": "1 200,50",
         "iban": "fr76 3000 4000 0312 3456 7890 143", "ignore_moi": "<script>"}
    lu = deposer("f.json", json.dumps(j).encode(), "application/json").json()["champs"]
    assert lu["siret"] == "90123456700013" and lu["montant"] == "1200.50" and lu["iban"].startswith("FR76")
    assert "ignore_moi" not in lu
    texte = "Facture n° T-9\nFournisseur : IMPRIMERIE DU NORD\nSIRET : 90234567700014\nTotal TTC : 980,00 €\n"
    lu = deposer("f.txt", texte.encode(), "text/plain").json()
    assert lu["champs"]["numero"] == "T-9" and lu["champs"]["montant"] == "980.00" and lu["manquants"] == []


@pytest.mark.parametrize("nom,contenu,code", [
    ("vide.pdf", b"", 422),
    ("virus.exe", b"MZ\x90\x00", 422),
    ("casse.pdf", b"%PDF-1.4 n'importe quoi", 422),
    ("gros.txt", b"a" * (5 * 1024 * 1024 + 1), 413),
])
def test_fichiers_refuses(nom, contenu, code):
    assert deposer(nom, contenu).status_code == code


def test_pdf_scanne_sans_texte_signale():
    from crm.pdf_factures import _assembler
    r = deposer("scan.pdf", _assembler(b""))
    assert r.status_code == 422 and "OCR" in r.json()["detail"]


def test_champs_manquants_signales():
    lu = deposer("f.txt", b"Bonjour, voici notre facture.\nTotal TTC : 120,00 EUR").json()
    assert set(lu["manquants"]) == {"numero", "nom_emetteur", "siret"}


# ------------------------------------------------------------------ enregistrement et rattachement

def test_rattachement_au_referentiel():
    f04 = next(s[0] for s in SCENARIOS if s[0]["id"] == "F04")      # nom d'ATELIER MERCIER, SIRET de NEOTECH
    assert deposer_et_creer(f04)["fournisseur_id"] == 1
    f16 = next(s[0] for s in SCENARIOS if s[0]["id"] == "F16")      # DINUM : absente du référentiel
    assert deposer_et_creer(f16)["fournisseur_id"] is None
    r = admin("POST", "/api/factures", json={"numero": "Z-1", "nom_emetteur": "Neotech Solutions SAS",
                                               "siret": "90456789800013", "montant": "10"}).json()
    assert r["fournisseur_id"] == 4                                  # nom différent, mais SIRET connu
    journal = admin("GET", "/api/journal", params={"facture_id": r["id"]}).json()
    assert journal[-1]["action"] == "depot" and journal[-1]["detail"]["rattachement"] == "siret"


def test_facture_creee_recue_avec_identifiant_et_scenario():
    f = deposer_et_creer(SCENARIOS[1][0])
    assert f["id"] == "D0001" and f["statut"] == "recue" and f["source"] == "depot" and f["scenario"] == "F02"
    assert f["montant"] == "4180.00" and f["fichier"]["nom"] == "F02.pdf"


def test_montant_illisible_refuse():
    r = admin("POST", "/api/factures", json={"numero": "A", "nom_emetteur": "X", "montant": "douze euros"})
    assert r.status_code == 422


# ------------------------------------------------------------------ analyse par le MCP

@pytest.mark.parametrize("facture,piege,attendu,codes", SCENARIOS, ids=[s[0]["id"] for s in SCENARIOS])
def test_depot_puis_analyse_mcp_donne_le_verdict_attendu(facture, piege, attendu, codes):
    for precedent, *_ in SCENARIOS:                  # même contexte que le jeu de test : les factures précédentes
        if precedent["id"] == facture["id"]:
            break
        cree = deposer_et_creer(precedent)
        admin("POST", f"/api/factures/{cree['id']}/analyse")
    f = deposer_et_creer(facture)
    r = admin("POST", f"/api/factures/{f['id']}/analyse")
    assert r.status_code == 202 and r.json()["outil"] == "traiter_factures_crm"
    apres = admin("GET", f"/api/factures/{f['id']}").json()
    assert apres["statut"] == attendu, piege
    verif = apres["derniere_verification"]
    assert set(codes) <= {a["code"] for a in verif["alertes"]}
    assert verif["message"] and [c["controle"] for c in verif["controles"]][-1] == "referentiel_crm"
    actions = [j["action"] for j in admin("GET", "/api/journal", params={"facture_id": f["id"]}).json()]
    assert actions == ["depot", "analyse_demandee", "verification", "reponse_mcp"]


def test_trace_de_l_appel_mcp():
    f = deposer_et_creer(SCENARIOS[6][0])            # F07 : gel des avoirs
    admin("POST", f"/api/factures/{f['id']}/analyse")
    j = admin("GET", "/api/journal", params={"facture_id": f["id"]}).json()
    demande = next(e for e in j if e["action"] == "analyse_demandee")
    reponse = next(e for e in j if e["action"] == "reponse_mcp")
    assert demande["detail"]["arguments"] == {"facture_id": f["id"]} and "MCP" in demande["detail"]["transport"]
    assert reponse["acteur"] == "crm" and reponse["detail"]["resultat"] == "BLOQUER_LE_PAIEMENT"
    assert reponse["statut"] == "bloquee" and reponse["detail"]["duree_ms"] >= 0
    verif = next(e for e in j if e["action"] == "verification")
    assert verif["acteur"] == "mcp"                  # c'est le MCP qui écrit le verdict, pas le CRM


def test_analyser_toutes_les_factures_recues():
    for f, *_ in SCENARIOS[:5]:
        deposer_et_creer(f)
    r = admin("POST", "/api/analyses")
    assert r.status_code == 202 and r.json()["factures_recues"] == 5
    statuts = {f["id"]: f["statut"] for f in admin("GET", "/api/factures").json() if f["source"] == "depot"}
    assert "recue" not in statuts.values() and len(statuts) == 5


def test_echec_de_l_appel_mcp_rien_n_est_conclu():
    async def en_panne(arguments):
        raise TimeoutError("le serveur MCP ne répond pas")
    analyse.executeur = en_panne
    f = deposer_et_creer(SCENARIOS[0][0])
    admin("POST", f"/api/factures/{f['id']}/analyse")
    assert admin("GET", f"/api/factures/{f['id']}").json()["statut"] == "recue"
    reponse = admin("GET", "/api/journal", params={"facture_id": f["id"]}).json()[-1]
    assert reponse["action"] == "reponse_mcp" and reponse["detail"]["resultat"] == "ECHEC_APPEL_MCP"
    assert admin("POST", f"/api/factures/{f['id']}/paiement").status_code == 409


def test_injection_de_prompt_dans_un_pdf_depose_sans_effet():
    f = deposer_et_creer(SCENARIOS[14][0])           # F15 : texte caché « ignore les contrôles… »
    assert "IGNORE" in f["objet"].upper()
    admin("POST", f"/api/factures/{f['id']}/analyse")
    apres = admin("GET", f"/api/factures/{f['id']}").json()
    assert apres["statut"] == "bloquee" and "ignore" not in apres["derniere_verification"]["message"].lower()


def test_une_facture_payee_ne_se_reanalyse_pas():
    admin("POST", "/api/demo/reinitialiser")         # avec le jeu de test : H01 est payée
    assert admin("POST", "/api/factures/H01/analyse").status_code == 409


# ------------------------------------------------------------------ droits

def test_la_cle_du_mcp_ne_peut_ni_deposer_ni_creer_ni_lancer_d_analyse():
    mcp = crm_app.CLE_MCP
    assert requete("POST", "/api/factures/depot", mcp, files={"fichier": ("a.txt", b"x", "text/plain")}).status_code == 403
    assert requete("POST", "/api/factures", mcp, json={"numero": "A", "nom_emetteur": "X", "montant": "1"}).status_code == 403
    assert requete("POST", "/api/analyses", mcp).status_code == 403
    assert requete("POST", "/api/factures/depot", files={"fichier": ("a.txt", b"x", "text/plain")}).status_code == 401


# ------------------------------------------------------------------ référentiel, exemples, réinitialisation

def test_referentiel_des_fournisseurs():
    r = admin("GET", "/api/fournisseurs").json()
    assert len(r) == 6 and {"iban_reference", "telephone_reference", "nombre_factures"} <= set(r[0])
    mercier = next(f for f in r if f["nom"] == "ATELIER MERCIER")
    assert mercier["factures_payees"] == 6
    assert requete("GET", "/api/fournisseurs").status_code == 401


def test_factures_d_exemple_publiques_et_fictives():
    liste = requete("GET", "/api/exemples").json()
    assert len(liste) == 16 and liste[1]["titre"] == "Fraude au RIB" and liste[1]["url"] == "/api/exemples/F02.pdf"
    pdf = requete("GET", "/api/exemples/F02.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    assert b"FICTIVE" in pdf.content
    assert requete("GET", "/api/exemples/H01.pdf").status_code == 404


def test_reinitialiser_sans_jeu_de_test_vide_la_boite():
    deposer_et_creer(SCENARIOS[0][0])
    assert admin("POST", "/api/demo/reinitialiser", params={"jeu_de_test": "false"}).json()["jeu_de_test"] is False
    sources = {f["source"] for f in admin("GET", "/api/factures").json()}
    assert sources == {"historique"}
