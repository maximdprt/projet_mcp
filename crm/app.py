"""CRM de démonstration (FastAPI + SQLite) : la base de factures que lit l'outil MCP `traiter_factures_crm`.

Lancement : uvicorn crm.app:app --port 8000      (ou double-clic sur LANCER_MCP_INSPECTOR.cmd)
Documentation interactive de l'API : http://127.0.0.1:8000/docs

À chaque démarrage, le CRM repart avec le jeu de test : 6 fournisseurs, un historique payé et 16 factures « recue »
(F01 à F16), chacune avec un piège de la fraude fournisseur (voir crm/donnees_demo.py).

Deux clés, deux droits (principe du moindre privilège) :
- CRM_CLE_MCP   : lire, et enregistrer le résultat d'une vérification. Rien d'autre.
- CRM_CLE_ADMIN : en plus, validation humaine, paiement (simulé), changement d'IBAN, réinitialisation.
Le CRM applique lui-même ses règles : il refuse de payer une facture qui n'est pas « verifiee » (HTTP 409),
et la clé du MCP ne peut ni valider ni payer (HTTP 403).
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import db

load_dotenv()
CLE_MCP = os.getenv("CRM_CLE_MCP", "cle-mcp-demo-a-changer").strip()
CLE_ADMIN = os.getenv("CRM_CLE_ADMIN", "cle-admin-demo-a-changer").strip()


def verifier_cles(cle_mcp: str, cle_admin: str) -> None:
    """Fail-closed : le CRM refuse de démarrer plutôt que de donner au MCP les droits d'un humain."""
    if not cle_mcp or not cle_admin:
        raise RuntimeError("CRM_CLE_MCP et CRM_CLE_ADMIN doivent être définies (fichier .env).")
    if cle_mcp == cle_admin:
        raise RuntimeError("CRM_CLE_MCP et CRM_CLE_ADMIN sont identiques : le MCP pourrait payer et valider "
                           "comme un humain. Mettez deux valeurs différentes dans le fichier .env.")


verifier_cles(CLE_MCP, CLE_ADMIN)

# Règles du CRM lui-même (pas des règles de vérification : celles-ci restent dans verif_fournisseur/regles.py)
STATUT_PAYABLE = "verifiee"              # seul statut qui autorise le paiement
STATUT_VALIDABLE = "a_verifier_humain"   # seul statut qu'un humain peut valider
STATUTS_FIGES = ("payee",)               # plus aucune modification
STATUTS_RETENUS = ("bloquee", "a_verifier_humain", "impossible_de_verifier")   # argent retenu (tableau de bord)


@asynccontextmanager
async def _cycle_de_vie(_app):
    db.initialiser(jeu_de_test=True)      # chaque démarrage repart des 16 factures du jeu de test
    yield


app = FastAPI(title="CRM de test — Vérif Fournisseur", version="2.0.0", lifespan=_cycle_de_vie)


@app.get("/", include_in_schema=False)
def accueil() -> dict:
    return {"crm": "Vérif Fournisseur (démo)", "documentation": "/docs",
            "usage": "Ce CRM est lu par l'outil MCP traiter_factures_crm. Testez le MCP avec le MCP Inspector."}


def role(x_api_key: str | None = Header(default=None)) -> str:
    if x_api_key == CLE_ADMIN:
        return "admin"
    if x_api_key == CLE_MCP:
        return "mcp"
    raise HTTPException(401, "Clé API absente ou invalide (en-tête X-API-Key).")


def admin(r: str = Depends(role)) -> str:
    if r != "admin":
        raise HTTPException(403, "Action réservée à un humain (clé administrateur). La clé du MCP ne peut pas "
                                 "valider, payer ni modifier un fournisseur.")
    return r


def _journal(c, facture_id, acteur, action, statut=None, detail=None):
    c.execute("INSERT INTO journal (facture_id, horodatage, acteur, action, statut, detail) VALUES (?,?,?,?,?,?)",
              (facture_id, db.maintenant(), acteur, action, statut, json.dumps(detail or {}, ensure_ascii=False)))


def _facture(c, facture_id: str) -> dict:
    f = db.ligne(c.execute("SELECT * FROM factures WHERE id=?", (facture_id,)).fetchone())
    if f is None:
        raise HTTPException(404, f"Facture {facture_id} introuvable.")
    return f


def _avec_actions(f: dict) -> dict:
    """Ce qu'un humain peut faire sur la facture. Calculé par le CRM, jamais par le client."""
    return {**f, "actions_possibles": {"payer": f["statut"] == STATUT_PAYABLE,
                                       "valider": f["statut"] == STATUT_VALIDABLE}}


# ------------------------------------------------------------------ lecture

@app.get("/api/session")
def session(r: str = Depends(role)) -> dict:
    """Rôle associé à la clé fournie (admin ou mcp)."""
    return {"role": r, "peut_agir": r == "admin"}


@app.get("/api/synthese")
def synthese(_: str = Depends(role)) -> dict:
    """Chiffres du tableau de bord. Montants en Decimal, rendus en chaînes (jamais de float)."""
    with db.connexion() as c:
        factures = [dict(r) for r in c.execute("SELECT statut, montant, devise, montant_eur FROM factures")]
    par_statut: dict[str, int] = {}
    retenu, paye, non_convertis = Decimal("0"), Decimal("0"), 0
    for f in factures:
        par_statut[f["statut"]] = par_statut.get(f["statut"], 0) + 1
        if f["montant_eur"]:
            m = Decimal(f["montant_eur"])
        elif f["devise"] == "EUR":
            m = Decimal(f["montant"])
        else:
            non_convertis += 1
            continue
        if f["statut"] in STATUTS_RETENUS:
            retenu += m
        elif f["statut"] == "payee":
            paye += m
    centimes = Decimal("0.01")
    return {"nombre_factures": len(factures), "par_statut": par_statut,
            "montant_retenu_eur": str(retenu.quantize(centimes, ROUND_HALF_UP)),
            "montant_paye_eur": str(paye.quantize(centimes, ROUND_HALF_UP)),
            "montants_non_convertis": non_convertis}


@app.get("/api/factures")
def lister_factures(statut: str | None = None, _: str = Depends(role)) -> list[dict]:
    with db.connexion() as c:
        req = "SELECT * FROM factures" + (" WHERE statut=?" if statut else "") + " ORDER BY id"
        return [_avec_actions(db.ligne(r)) for r in c.execute(req, (statut,) if statut else ())]


@app.get("/api/factures/{facture_id}")
def lire_facture(facture_id: str, _: str = Depends(role)) -> dict:
    with db.connexion() as c:
        return _avec_actions(_facture(c, facture_id))


@app.get("/api/fournisseurs")
def lister_fournisseurs(_: str = Depends(role)) -> list[dict]:
    """Le référentiel : les fournisseurs connus, leur IBAN et leur téléphone de référence (contre-appel)."""
    with db.connexion() as c:
        return [db.ligne(r) for r in c.execute(
            "SELECT f.*, (SELECT COUNT(*) FROM factures WHERE fournisseur_id=f.id) AS nombre_factures, "
            "(SELECT COUNT(*) FROM factures WHERE fournisseur_id=f.id AND statut='payee') AS factures_payees "
            "FROM fournisseurs f ORDER BY f.nom")]


@app.get("/api/fournisseurs/{fournisseur_id}")
def lire_fournisseur(fournisseur_id: int, _: str = Depends(role)) -> dict:
    with db.connexion() as c:
        f = db.ligne(c.execute("SELECT * FROM fournisseurs WHERE id=?", (fournisseur_id,)).fetchone())
    if f is None:
        raise HTTPException(404, "Fournisseur introuvable.")
    return f


@app.get("/api/fournisseurs/{fournisseur_id}/factures")
def factures_fournisseur(fournisseur_id: int, _: str = Depends(role)) -> list[dict]:
    with db.connexion() as c:
        return [db.ligne(r) for r in c.execute(
            "SELECT id, numero, montant, devise, montant_eur, date_emission, statut FROM factures "
            "WHERE fournisseur_id=? ORDER BY date_emission", (fournisseur_id,))]


@app.get("/api/journal")
def journal(facture_id: str | None = None, depuis: int | None = None, _: str = Depends(role)) -> list[dict]:
    """Journal d'audit. `depuis` : seulement les entrées plus récentes que cet identifiant (suivi en direct)."""
    conditions, valeurs = [], []
    if facture_id:
        conditions.append("facture_id=?")
        valeurs.append(facture_id)
    if depuis is not None:
        conditions.append("id>?")
        valeurs.append(depuis)
    req = "SELECT * FROM journal" + (" WHERE " + " AND ".join(conditions) if conditions else "") + " ORDER BY id"
    with db.connexion() as c:
        return [db.ligne(r) for r in c.execute(req, valeurs)]


@app.get("/api/scenarios")
def scenarios(_: str = Depends(role)) -> list[dict]:
    """Les 16 scénarios de test : le piège de chaque facture et le résultat attendu (phase de test)."""
    from .donnees_demo import CHAMPS_PIEGES, SCENARIOS, TITRES_SCENARIOS
    return [{"facture_id": f["id"], "titre": TITRES_SCENARIOS.get(f["id"], f["id"]), "piege": piege,
             "statut_attendu": attendu, "codes_attendus": list(codes), "champs_pieges": CHAMPS_PIEGES.get(f["id"], [])}
            for f, piege, attendu, codes in SCENARIOS]


# ------------------------------------------------------------------ écriture du MCP (résultat seulement)

class Controle(BaseModel):
    """Résumé d'un contrôle du MCP (nom, source, résultat) : jamais les données détaillées."""
    controle: str = Field(max_length=40)
    source: str = Field(max_length=120)
    resultat: Literal["OK", "ALERTE", "INDISPONIBLE", "NON_DEMANDE"]
    raison: str | None = Field(default=None, max_length=200)


class Verification(BaseModel):
    statut: Literal["verifiee", "a_verifier_humain", "bloquee", "impossible_de_verifier"]
    statut_mcp: str = Field(max_length=40)
    montant_eur: str | None = Field(default=None, max_length=20)
    alertes: list[dict] = Field(default_factory=list, max_length=50)
    controles: list[Controle] = Field(default_factory=list, max_length=20)
    message: str | None = Field(default=None, max_length=400)
    empreinte: str = Field(min_length=64, max_length=64)
    mode: str = Field(default="reel", max_length=20)


@app.post("/api/factures/{facture_id}/verification")
def enregistrer_verification(facture_id: str, v: Verification, qui: str = Depends(role)) -> dict:
    with db.connexion() as c:
        f = _facture(c, facture_id)
        if f["statut"] in STATUTS_FIGES:
            raise HTTPException(409, "Facture déjà payée : son statut ne peut plus changer.")
        c.execute("UPDATE factures SET statut=?, montant_eur=?, derniere_verification=? WHERE id=?",
                  (v.statut, v.montant_eur, json.dumps(v.model_dump(), ensure_ascii=False), facture_id))
        _journal(c, facture_id, qui, "verification", v.statut,
                 {"statut_mcp": v.statut_mcp, "codes": [a.get("code") for a in v.alertes], "empreinte": v.empreinte,
                  "mode": v.mode})
        n = c.execute("SELECT max(id) FROM journal").fetchone()[0]
    return {"enregistre": True, "facture_id": facture_id, "statut": v.statut, "journal_id": n}


# ------------------------------------------------------------------ actions humaines (clé admin)

class ValidationHumaine(BaseModel):
    valideur: str = Field(min_length=2, max_length=80)
    commentaire: str = Field(min_length=10, max_length=500)


@app.post("/api/factures/{facture_id}/validation-humaine")
def validation_humaine(facture_id: str, v: ValidationHumaine, qui: str = Depends(admin)) -> dict:
    with db.connexion() as c:
        f = _facture(c, facture_id)
        if f["statut"] != STATUT_VALIDABLE:
            raise HTTPException(409, f"Seule une facture « a_verifier_humain » peut être validée (ici : {f['statut']}). "
                                     "Une facture bloquée doit être corrigée puis revérifiée.")
        c.execute("UPDATE factures SET statut=? WHERE id=?", (STATUT_PAYABLE, facture_id))
        _journal(c, facture_id, f"{qui}:{v.valideur}", "validation_humaine", STATUT_PAYABLE, v.model_dump())
    return {"facture_id": facture_id, "statut": STATUT_PAYABLE}


@app.post("/api/factures/{facture_id}/paiement")
def payer(facture_id: str, qui: str = Depends(admin)) -> dict:
    with db.connexion() as c:
        f = _facture(c, facture_id)
        if f["statut"] != STATUT_PAYABLE:
            raise HTTPException(409, f"Paiement refusé : la facture doit être « verifiee » (ici : {f['statut']}).")
        c.execute("UPDATE factures SET statut='payee' WHERE id=?", (facture_id,))
        _journal(c, facture_id, qui, "paiement_simule", "payee", {"montant": f["montant"], "devise": f["devise"]})
    return {"facture_id": facture_id, "statut": "payee", "note": "paiement simulé"}


class NouvelIban(BaseModel):
    iban: str = Field(min_length=15, max_length=34)
    preuve_contre_appel: str = Field(min_length=10, max_length=300)


@app.put("/api/fournisseurs/{fournisseur_id}/iban")
def changer_iban(fournisseur_id: int, n: NouvelIban, qui: str = Depends(admin)) -> dict:
    with db.connexion() as c:
        c.execute("UPDATE fournisseurs SET iban_reference=? WHERE id=?", (n.iban.replace(" ", "").upper(), fournisseur_id))
        _journal(c, None, qui, "changement_iban", None, {"fournisseur_id": fournisseur_id, **n.model_dump()})
    return {"fournisseur_id": fournisseur_id, "iban_reference": n.iban}


@app.post("/api/demo/reinitialiser")
def reinitialiser(jeu_de_test: bool = True, _: str = Depends(admin)) -> dict:
    """Remet la démo à zéro. jeu_de_test=false : boîte de réception vide (on dépose les factures soi-même)."""
    db.initialiser(jeu_de_test=jeu_de_test)
    return {"reinitialise": True, "jeu_de_test": jeu_de_test}
