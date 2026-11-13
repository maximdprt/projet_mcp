"""Vérif Fournisseur — SaaS de démonstration (FastAPI + SQLite) : on dépose une facture, le MCP l'analyse.

Lancement : uvicorn crm.app:app --port 8000      Interface : http://127.0.0.1:8000
Documentation interactive de l'API : http://127.0.0.1:8000/docs

Deux clés, deux droits (principe du moindre privilège) :
- CRM_CLE_MCP   : lire, et enregistrer le résultat d'une vérification. Rien d'autre.
- CRM_CLE_ADMIN : en plus, validation humaine, paiement, changement d'IBAN, réinitialisation.
Le CRM applique lui-même ses règles : il refuse de payer une facture qui n'est pas « verifiee ».

Parcours : dépôt d'un fichier (extraction.py) -> enregistrement et rattachement au référentiel (ingestion.py)
-> analyse : le CRM appelle le serveur MCP par le protocole MCP (analyse.py) ; c'est le MCP qui lit la facture,
interroge les sources, applique les règles et écrit le verdict -> décision humaine (validation, paiement simulé).

L'interface web (crm/interface/) ne contient aucune clé : elle la demande à l'utilisateur, la garde dans
l'onglet (sessionStorage) et n'appelle que l'API ci-dessous. Elle ne décide rien : les actions possibles
sont calculées ici (`actions_possibles`) et le serveur revérifie tout à chaque appel.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analyse, db, extraction, ingestion

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

DOSSIER_INTERFACE = Path(__file__).with_name("interface")

# Règles du CRM lui-même (pas des règles de vérification : celles-ci restent dans verif_fournisseur/regles.py)
STATUT_PAYABLE = "verifiee"              # seul statut qui autorise le paiement
STATUT_VALIDABLE = "a_verifier_humain"   # seul statut qu'un humain peut valider
STATUTS_FIGES = ("payee",)               # plus aucune modification
STATUTS_RETENUS = ("bloquee", "a_verifier_humain", "impossible_de_verifier")   # argent retenu (tableau de bord)



@asynccontextmanager
async def _cycle_de_vie(_app):
    if not os.path.exists(db.CHEMIN) or not db.schema_a_jour():
        db.initialiser(jeu_de_test=False)        # première exécution : boîte de réception vide
    yield


app = FastAPI(title="CRM de test — Vérif Fournisseur", version="1.0.0", lifespan=_cycle_de_vie)


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
    """Ce qu'un humain peut faire sur la facture. Calculé ici pour que l'interface n'ait aucune règle à elle."""
    return {**f, "actions_possibles": {"payer": f["statut"] == STATUT_PAYABLE,
                                       "valider": f["statut"] == STATUT_VALIDABLE}}


# ------------------------------------------------------------------ lecture

@app.get("/api/session")
def session(r: str = Depends(role)) -> dict:
    """Rôle associé à la clé fournie : l'interface s'en sert pour vérifier la clé saisie."""
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


# ------------------------------------------------------------------ dépôt d'une facture et analyse par le MCP

@app.post("/api/factures/depot")
async def deposer(fichier: UploadFile = File(...), _: str = Depends(admin)) -> dict:
    """Lit un fichier déposé (PDF, TXT, JSON) et renvoie les champs extraits. Rien n'est encore enregistré :
    l'utilisateur relit et corrige avant de créer la facture."""
    contenu = await fichier.read(extraction.TAILLE_MAX + 1)
    if len(contenu) > extraction.TAILLE_MAX:
        raise HTTPException(413, "Fichier trop volumineux (5 Mo maximum).")
    nom = (fichier.filename or "facture").replace("\\", "/").split("/")[-1][:120]
    try:
        resultat = extraction.extraire(nom, contenu)
    except extraction.FichierRefuse as e:
        raise HTTPException(422, str(e)) from None
    return {**resultat, "fichier": {"nom": nom, "taille": len(contenu), "empreinte": hashlib.sha256(contenu).hexdigest()}}


class NouvelleFacture(BaseModel):
    numero: str = Field(min_length=1, max_length=40)
    nom_emetteur: str = Field(min_length=1, max_length=120)
    siret: str | None = Field(default=None, max_length=20)
    tva: str | None = Field(default=None, max_length=20)
    iban: str | None = Field(default=None, max_length=40)
    adresse_emetteur: str | None = Field(default=None, max_length=200)
    montant: str = Field(min_length=1, max_length=20)
    devise: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    date_emission: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    objet: str | None = Field(default=None, max_length=500)
    nom_fichier: str | None = Field(default=None, max_length=120)
    empreinte_fichier: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def _sans_espaces(valeur: str | None) -> str | None:
    return (valeur or "").replace(" ", "").upper() or None


@app.post("/api/factures", status_code=201)
def creer_facture(n: NouvelleFacture, qui: str = Depends(admin)) -> dict:
    """Enregistre une facture déposée (statut « recue ») et la rattache au référentiel. Aucune vérification ici."""
    montant = extraction.normaliser_montant(n.montant)
    if montant is None:
        raise HTTPException(422, "Montant illisible.")
    with db.connexion() as c:
        fournisseur_id, mode = ingestion.rattacher(c, n.nom_emetteur, n.siret)
        facture_id = ingestion.nouvel_identifiant(c)
        scenario = ingestion.scenario_correspondant(n.numero.strip(), n.nom_emetteur)
        fichier = {"nom": n.nom_fichier, "empreinte": n.empreinte_fichier} if n.nom_fichier else None
        c.execute("INSERT INTO factures (id, numero, fournisseur_id, nom_emetteur, siret, tva, iban, adresse_emetteur, "
                  "montant, devise, date_emission, objet, statut, source, scenario, fichier) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'recue','depot',?,?)",
                  (facture_id, n.numero.strip(), fournisseur_id, n.nom_emetteur.strip(), _sans_espaces(n.siret),
                   _sans_espaces(n.tva), _sans_espaces(n.iban), (n.adresse_emetteur or "").strip() or None, montant,
                   n.devise, n.date_emission, (n.objet or "").strip() or None, scenario,
                   json.dumps(fichier, ensure_ascii=False) if fichier else None))
        _journal(c, facture_id, qui, "depot", "recue",
                 {"fichier": n.nom_fichier, "empreinte_fichier": n.empreinte_fichier, "fournisseur_id": fournisseur_id,
                  "rattachement": mode, "scenario": scenario})
        return _avec_actions(_facture(c, facture_id))


async def _faire_analyser(arguments: dict, facture_id: str | None) -> None:
    """Tâche de fond : appel de l'outil MCP, puis trace de la réponse dans le journal."""
    debut = time.monotonic()
    try:
        r = await analyse.executeur(arguments)
    except Exception as e:  # MCP introuvable, délai dépassé, plantage : la facture reste « recue »
        r = {"erreur": "ECHEC_APPEL_MCP", "raison": type(e).__name__}
    detail = {"outil": analyse.OUTIL, "duree_ms": int((time.monotonic() - debut) * 1000),
              "resultat": r.get("statut") or r.get("erreur") or ("REFUS" if r.get("refus") else "OK"),
              "nombre_traitees": r.get("nombre_traitees", 1 if r.get("statut") else 0)}
    if r.get("erreur") or r.get("refus"):
        detail["raison"] = str(r.get("raison") or r.get("motif") or "")[:200]
    with db.connexion() as c:
        _journal(c, facture_id, "crm", "reponse_mcp", r.get("statut_crm"), detail)


@app.post("/api/factures/{facture_id}/analyse", status_code=202)
def analyser_facture(facture_id: str, taches: BackgroundTasks, qui: str = Depends(admin)) -> dict:
    """Fait analyser la facture par le serveur MCP (outil traiter_factures_crm). Réponse immédiate ; le verdict
    arrive dans le journal (action « verification », écrite par le MCP lui-même)."""
    arguments = {"facture_id": facture_id}
    with db.connexion() as c:
        f = _facture(c, facture_id)
        if f["statut"] in STATUTS_FIGES:
            raise HTTPException(409, "Facture déjà payée : rien à analyser.")
        _journal(c, facture_id, qui, "analyse_demandee", None,
                 {"outil": analyse.OUTIL, "arguments": arguments, "transport": "stdio (protocole MCP)"})
    taches.add_task(_faire_analyser, arguments, facture_id)
    return {"analyse": "lancee", "facture_id": facture_id, "outil": analyse.OUTIL, "arguments": arguments}


@app.post("/api/analyses", status_code=202)
def analyser_tout(taches: BackgroundTasks, qui: str = Depends(admin)) -> dict:
    """Fait analyser par le MCP toutes les factures « recue » (25 au plus par appel, limite de l'outil)."""
    with db.connexion() as c:
        n = c.execute("SELECT COUNT(*) FROM factures WHERE statut='recue'").fetchone()[0]
        _journal(c, None, qui, "analyse_demandee", None,
                 {"outil": analyse.OUTIL, "arguments": {}, "transport": "stdio (protocole MCP)", "factures": n})
    taches.add_task(_faire_analyser, {}, None)
    return {"analyse": "lancee", "outil": analyse.OUTIL, "arguments": {}, "factures_recues": n}


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


# ------------------------------------------------------------------ factures d'exemple (fictives, publiques)

def _exemple(exemple_id: str):
    from .donnees_demo import SCENARIOS, TITRES_SCENARIOS
    for f, piege, attendu, _codes in SCENARIOS:
        if f["id"] == exemple_id:
            return f, piege, attendu, TITRES_SCENARIOS.get(f["id"], f["id"])
    raise HTTPException(404, "Exemple introuvable.")


@app.get("/api/exemples")
def exemples() -> list[dict]:
    """Les 16 factures PDF du jeu de test, à télécharger ou à glisser dans la zone de dépôt. Données fictives."""
    from .donnees_demo import SCENARIOS
    sortie = []
    for f, *_ in SCENARIOS:
        _, piege, attendu, titre = _exemple(f["id"])
        sortie.append({"id": f["id"], "titre": titre, "piege": piege, "statut_attendu": attendu,
                       "nom_emetteur": f["nom_emetteur"], "numero": f["numero"], "montant": f["montant"],
                       "devise": f["devise"], "url": f"/api/exemples/{f['id']}.pdf",
                       "nom_fichier": f"facture-{f['numero']}.pdf"})
    return sortie


@app.get("/api/exemples/{exemple_id}.pdf")
def exemple_pdf(exemple_id: str) -> Response:
    from .pdf_factures import facture_pdf
    f, *_ = _exemple(exemple_id)
    return Response(facture_pdf(f), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="facture-{f["numero"]}.pdf"',
                             "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------ interface web (aucune clé dedans)

# La page n'exécute que ses propres fichiers et ne parle qu'à ce serveur : un texte piégé dans une facture
# ne peut ni charger de script, ni envoyer la clé ailleurs.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


@app.get("/", include_in_schema=False)
def interface() -> FileResponse:
    return FileResponse(DOSSIER_INTERFACE / "index.html", media_type="text/html",
                        headers={"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})


app.mount("/interface", StaticFiles(directory=DOSSIER_INTERFACE), name="interface")
