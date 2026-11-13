"""API BODACC (DILA, data.gouv.fr) : procédures collectives, radiations, conciliations.

Ouverte, sans clé, Licence Ouverte 2.0.
Garde-fous : seules les annonces dont l'entreprise est le SUJET (vérifié par son SIREN) sont gardées ;
jugements visant une personne (faillite personnelle…) écartés ; aucun nom de personne renvoyé.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .http import SourceIndisponible, get_json, texte

URL = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
URL_ANNONCE = "https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:{id}"
SOURCE = "API BODACC (DILA)"
FAMILLES = ("collective", "radiation", "conciliation", "retablissement_professionnel")
JUGEMENTS_PERSONNELS = ("faillite personnelle", "interdiction de gérer", "interdiction de diriger")


def _json(valeur: Any) -> Any:
    if isinstance(valeur, (dict, list)):
        return valeur
    try:
        return json.loads(valeur) if valeur else None
    except (TypeError, ValueError):
        return None


def _sirens_sujets(listepersonnes: Any) -> set[str]:
    data = _json(listepersonnes)
    personnes = data.get("personne") if isinstance(data, dict) else None
    if isinstance(personnes, dict):
        personnes = [personnes]
    sirens = set()
    for p in personnes or []:
        imm = p.get("numeroImmatriculation") if isinstance(p, dict) else None
        if isinstance(imm, dict):
            sirens.add(re.sub(r"\D", "", str(imm.get("numeroIdentification") or "")))
    return sirens


def reduire(record: dict, siren: str) -> dict | None:
    sujets = _sirens_sujets(record.get("listepersonnes"))
    if sujets and siren not in sujets:
        return None  # l'entreprise est seulement mentionnée (acheteur, créancier…)
    jugement = _json(record.get("jugement")) or {}
    nature = texte(jugement.get("nature")) if isinstance(jugement, dict) else None
    if nature and any(p in nature.lower() for p in JUGEMENTS_PERSONNELS):
        return None
    annonce_id = str(record.get("id") or "").strip()
    return {
        "date_parution": str(record.get("dateparution") or "")[:10] or None,
        "famille": record.get("familleavis"),
        "nature_jugement": nature,
        "tribunal": texte(record.get("tribunal"), 120),
        "lien_annonce": URL_ANNONCE.format(id=annonce_id) if annonce_id else None,
    }


async def lire(client: httpx.AsyncClient, siren: str) -> list[dict]:
    familles = " or ".join(f'familleavis="{f}"' for f in FAMILLES)
    params = {
        "where": f'registre="{siren}" and ({familles})',
        "order_by": "dateparution desc",
        "limit": 100,
        "select": "id,dateparution,familleavis,typeavis,tribunal,jugement,listepersonnes",
    }
    data = await get_json(client, URL, params, SOURCE)
    if not isinstance(data, dict) or "results" not in data:
        raise SourceIndisponible(SOURCE, "réponse inattendue (pas de champ 'results')")
    return [a for a in (reduire(r, siren) for r in data["results"]) if a]
