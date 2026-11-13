"""API Gels des avoirs (DG Trésor, data.gouv.fr) : registre national des sanctions financières.

Ouverte, sans clé, User-Agent obligatoire. Le registre recense les personnes et entités visées par
un gel d'avoirs en France (mesures nationales, UE et ONU). Mettre des fonds à leur disposition est
interdit : un paiement à une entité inscrite doit être bloqué.

Le fichier complet (plusieurs Mo) est téléchargé puis gardé en mémoire quelques heures.
"""

from __future__ import annotations

import re
import time
import unicodedata

import httpx

from .. import config
from .http import SourceIndisponible, get_json, texte

URL = "https://gels-avoirs.dgtresor.gouv.fr/ApiPublic/api/v1/publication/derniere-publication-fichier-json"
SOURCE = "API Gels des avoirs (DG Trésor)"

FORMES = {"SAS", "SASU", "SARL", "EURL", "SA", "SNC", "SCI", "LLC", "LTD", "LIMITED", "INC", "GMBH", "BV",
          "JSC", "PJSC", "OJSC", "CJSC", "OOO", "AO", "PAO", "ZAO", "CO", "CORP", "COMPANY", "SPA", "SRL"}

_cache: dict = {"expire": 0.0, "entrees": None, "date_publication": None}


def vider_cache() -> None:
    _cache.update(expire=0.0, entrees=None, date_publication=None)


def normaliser(nom: str | None) -> str:
    s = unicodedata.normalize("NFKD", str(nom or "")).encode("ascii", "ignore").decode().upper()
    mots = [m for m in re.split(r"[^A-Z0-9]+", s) if m and m not in FORMES]
    return " ".join(mots)


def _valeur(v: object, cle: str) -> str:
    if isinstance(v, dict):
        for k, val in v.items():
            if k.lower() == cle.lower() and val:
                return str(val)
        return ""
    return str(v or "")


def _indexer(data: dict) -> tuple[list[dict], str | None]:
    pub = data.get("Publications") or {}
    if isinstance(pub, list):
        pub = pub[0] if pub else {}
    entrees = []
    for rec in pub.get("PublicationDetail") or []:
        nature = str(rec.get("Nature") or "").strip()
        if nature.lower() == "navire":
            continue
        prenom = ""
        noms = [str(rec.get("Nom") or "")]
        for d in rec.get("RegistreDetail") or []:
            champ = str(d.get("TypeChamp") or "").upper()
            valeurs = d.get("Valeur") if isinstance(d.get("Valeur"), list) else [d.get("Valeur")]
            if champ == "ALIAS":
                noms += [_valeur(v, "Alias") for v in valeurs]
            elif champ == "PRENOM" and not prenom:
                prenom = next((_valeur(v, "Prenom") for v in valeurs if _valeur(v, "Prenom")), "")
        if nature.lower() == "personne physique" and prenom:
            noms = [f"{prenom} {n}" for n in noms if n] + [f"{n} {prenom}" for n in noms if n]
        normalises = sorted({normaliser(n) for n in noms if normaliser(n)})
        if normalises:
            entrees.append({"id_registre": rec.get("IdRegistre"), "nature": nature,
                            "nom_inscrit": texte(rec.get("Nom"), 120), "noms": normalises})
    return entrees, str(pub.get("DatePublication") or "")[:10] or None


async def charger(client: httpx.AsyncClient) -> tuple[list[dict], str | None]:
    if _cache["entrees"] is not None and time.monotonic() < _cache["expire"]:
        return _cache["entrees"], _cache["date_publication"]
    data = await get_json(client, URL, None, SOURCE, timeout=config.TIMEOUT_GELS_SECONDES)
    entrees, date_pub = _indexer(data if isinstance(data, dict) else {})
    if not entrees:
        raise SourceIndisponible(SOURCE, "registre vide ou format inattendu")
    _cache.update(entrees=entrees, date_publication=date_pub,
                  expire=time.monotonic() + config.CACHE_GELS_HEURES * 3600)
    return entrees, date_pub


async def rechercher(client: httpx.AsyncClient, noms: list[str], inclure_personnes: bool) -> dict:
    """Correspondance exacte (nom normalisé identique) ou partielle (tous les mots d'un nom inscrit,
    au moins 2, présents dans le nom du fournisseur)."""
    entrees, date_pub = await charger(client)
    cibles = {normaliser(n) for n in noms if normaliser(n)}
    exactes, partielles = [], []
    for e in entrees:
        if e["nature"].lower() == "personne physique" and not inclure_personnes:
            continue
        for inscrit in e["noms"]:
            mots = set(inscrit.split())
            if inscrit in cibles:
                exactes.append(e)
                break
            if len(mots) >= 2 and any(mots <= set(c.split()) for c in cibles):
                partielles.append(e)
                break
    def garder(liste: list[dict]) -> list[dict]:
        return [{k: e[k] for k in ("id_registre", "nature", "nom_inscrit")} for e in liste[:5]]

    return {"date_publication_registre": date_pub, "correspondances_exactes": garder(exactes),
            "correspondances_partielles": garder(partielles), "nombre_entrees_registre": len(entrees)}
