"""PREUVES D'UTILITÉ : les 16 factures piégées du CRM, traitées par le vrai outil traiter_factures_crm.

Ces tests montrent ce que le MCP empêche concrètement, et qu'il ne peut pas payer lui-même.
"""

import asyncio

import httpx
import pytest
from conftest import RE, FausseAPI

from crm.donnees_demo import IBAN_MERCIER, SCENARIOS
from harnais import base_temporaire, client_admin, clients
from verif_fournisseur import outils as v


@pytest.fixture(autouse=True)
def crm_neuf():
    base_temporaire()


def traiter(facture_id=None, transport=None):
    async def _run():
        async with clients(transport) as (ext, crm):
            return await v.traiter_factures_crm(ext, crm, facture_id)
    return asyncio.run(_run())


def crm_admin(methode, chemin, **kw):
    async def _run():
        async with client_admin() as c:
            return await c.request(methode, chemin, **kw)
    return asyncio.run(_run())


def crm_mcp(methode, chemin, **kw):
    async def _run():
        async with clients() as (_, crm):
            return await crm.request(methode, chemin, **kw)
    return asyncio.run(_run())


@pytest.mark.parametrize("facture,piege,attendu,codes_attendus", SCENARIOS, ids=[s[0]["id"] for s in SCENARIOS])
def test_scenario(facture, piege, attendu, codes_attendus):
    r = traiter(facture["id"])
    assert r["statut_crm"] == attendu, piege
    assert set(codes_attendus) <= {a["code"] for a in r["alertes"]}, piege
    assert crm_admin("GET", f"/api/factures/{facture['id']}").json()["statut"] == attendu


def test_lot_complet_seules_les_factures_saines_passent():
    r = traiter()
    assert r["nombre_traitees"] == 16
    assert r["synthese"] == {"AUCUNE_ALERTE_DETECTEE": 2, "BLOQUER_LE_PAIEMENT": 9, "VERIFICATION_HUMAINE_REQUISE": 5}
    verifiees = {f["facture_id"] for f in r["factures"] if f["statut"] == "AUCUNE_ALERTE_DETECTEE"}
    assert verifiees == {"F01", "F12"}


def test_le_mcp_ne_peut_ni_payer_ni_valider_ni_changer_un_iban():
    traiter("F01")
    assert crm_mcp("POST", "/api/factures/F01/paiement").status_code == 403
    assert crm_mcp("POST", "/api/factures/F09/validation-humaine",
                   json={"valideur": "IA", "commentaire": "je valide tout seul"}).status_code == 403
    assert crm_mcp("PUT", "/api/fournisseurs/1/iban",
                   json={"iban": "LT121000011101001000", "preuve_contre_appel": "aucune"}).status_code == 403


def test_le_crm_refuse_de_demarrer_si_les_deux_cles_sont_identiques():
    from crm.app import verifier_cles
    with pytest.raises(RuntimeError, match="identiques"):
        verifier_cles("1234", "1234")                 # sinon la clé du MCP serait aussi la clé admin
    with pytest.raises(RuntimeError):
        verifier_cles("", "admin")
    verifier_cles("cle-mcp", "cle-admin")             # deux clés différentes : accepté


def test_le_crm_refuse_de_payer_une_facture_bloquee_meme_pour_un_humain():
    traiter("F02")
    assert crm_admin("POST", "/api/factures/F02/paiement").status_code == 409
    assert crm_admin("POST", "/api/factures/F01/paiement").status_code == 409   # pas encore vérifiée
    traiter("F01")
    assert crm_admin("POST", "/api/factures/F01/paiement").status_code == 200


def test_validation_humaine_puis_paiement_pour_un_cas_douteux():
    traiter("F09")
    assert crm_admin("POST", "/api/factures/F09/paiement").status_code == 409
    ok = crm_admin("POST", "/api/factures/F09/validation-humaine",
                   json={"valideur": "Directrice financière", "commentaire": "Commande exceptionnelle confirmée."})
    assert ok.status_code == 200
    assert crm_admin("POST", "/api/factures/F09/paiement").status_code == 200


def test_injection_de_prompt_dans_la_facture_sans_effet():
    r = traiter("F15")
    assert r["statut_crm"] == "bloquee"
    assert "ignore" not in r["message"].lower()


def test_l_iban_de_reference_n_est_jamais_modifie():
    traiter()
    assert crm_admin("GET", "/api/fournisseurs/1").json()["iban_reference"] == IBAN_MERCIER


def test_chaque_verification_laisse_une_trace_d_audit():
    traiter("F02")
    journal = crm_admin("GET", "/api/journal", params={"facture_id": "F02"}).json()
    trace = journal[-1]
    assert trace["acteur"] == "mcp" and trace["statut"] == "bloquee"
    assert len(trace["detail"]["empreinte"]) == 64
    assert "IBAN_DIFFERENT_DU_REFERENTIEL" in trace["detail"]["codes"]


def test_api_externe_en_panne_la_facture_reste_impayable():
    api = FausseAPI()
    api.pannes = {RE: "timeout"}
    r = traiter("F01", transport=api.transport())
    assert r["statut_crm"] == "impossible_de_verifier"
    assert crm_admin("POST", "/api/factures/F01/paiement").status_code == 409


def test_crm_injoignable_rien_n_est_modifie():
    async def _run():
        async with clients() as (ext, _):
            def coupe(request):
                raise httpx.ConnectError("CRM éteint")
            async with httpx.AsyncClient(transport=httpx.MockTransport(coupe), base_url="http://crm") as crm:
                return await v.traiter_factures_crm(ext, crm, "F01")
    r = asyncio.run(_run())
    assert r["erreur"] == "SOURCE_INDISPONIBLE" and "Rien n'a été modifié" in r["consigne"]
    assert crm_admin("GET", "/api/factures/F01").json()["statut"] == "recue"


def test_une_facture_deja_payee_n_est_pas_modifiee():
    r = traiter("H01")
    assert r["refus"] and crm_admin("GET", "/api/factures/H01").json()["statut"] == "payee"


def test_mauvaise_cle_crm_refusee():
    async def _run():
        async with clients(cle="mauvaise-cle") as (ext, crm):
            return await v.traiter_factures_crm(ext, crm, "F01")
    assert asyncio.run(_run())["erreur"] == "SOURCE_INDISPONIBLE"
