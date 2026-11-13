"""API Recherche d'entreprises (DINUM, data.gouv.fr) : identité et état d'une entreprise.

Ouverte, sans clé, 7 appels/s. Données Sirene (INSEE) + RNE (INPI).
Garde-fous : correspondance EXACTE du SIREN (la recherche est floue) ; dirigeants, élus et
finances jamais copiés (liste blanche).
"""

from __future__ import annotations

from typing import Any

import httpx

from .. import config
from .http import Limiteur, get_json, texte

URL = "https://recherche-entreprises.api.gouv.fr/search"
URL_FICHE = "https://annuaire-entreprises.data.gouv.fr/entreprise/{siren}"
SOURCE = "API Recherche d'entreprises (DINUM)"
LIMITEUR = Limiteur(config.APPELS_PAR_SECONDE)


def _enseignes(result: dict) -> list[str]:
    noms: list[str] = []
    for etab in [result.get("siege") or {}] + list(result.get("matching_etablissements") or []):
        noms.extend(etab.get("liste_enseignes") or [])
        if etab.get("nom_commercial"):
            noms.append(etab["nom_commercial"])
    return sorted({n for n in (texte(x, 100) for x in noms) if n})


def _etablissement(etab: dict) -> dict:
    return {
        "siret": etab.get("siret"),
        "est_siege": bool(etab.get("est_siege")),
        "etat": "ouvert" if etab.get("etat_administratif") == "A" else "fermé",
        "date_fermeture": etab.get("date_fermeture") or None,
        "adresse": texte(etab.get("adresse")),
        "code_postal": etab.get("code_postal"),
        "commune_insee": etab.get("commune"),
    }


def extraire(result: dict, siret: str | None = None) -> dict:
    """Liste blanche des champs conservés. Rien sur les personnes."""
    siege = result.get("siege") or {}
    fiche = {
        "siren": result.get("siren"),
        "nom_officiel": texte(result.get("nom_raison_sociale") or result.get("nom_complet")),
        "nom_complet": texte(result.get("nom_complet")),
        "sigle": texte(result.get("sigle"), 50),
        "enseignes": _enseignes(result),
        "etat_administratif": "active" if result.get("etat_administratif") == "A" else "cessée",
        "date_creation": result.get("date_creation") or None,
        "date_fermeture": result.get("date_fermeture") or None,
        "nature_juridique": result.get("nature_juridique"),
        "activite_naf": result.get("activite_principale"),
        "est_entrepreneur_individuel": bool((result.get("complements") or {}).get("est_entrepreneur_individuel")),
        "diffusion_complete": result.get("statut_diffusion", "O") == "O",
        "siege": _etablissement(siege) if siege else None,
        "date_mise_a_jour_source": result.get("date_mise_a_jour") or None,
        "lien_fiche_publique": URL_FICHE.format(siren=result.get("siren")),
    }
    if siret:
        candidats = list(result.get("matching_etablissements") or []) + ([siege] if siege else [])
        trouve = next((e for e in candidats if e.get("siret") == siret), None)
        fiche["etablissement_demande"] = _etablissement(trouve) if trouve else None
    return fiche


async def chercher_par_nom(client: httpx.AsyncClient, nom: str, code_postal: str | None = None) -> dict:
    params: dict[str, Any] = {"q": nom, "per_page": 5, "page": 1, "limite_matching_etablissements": 3}
    if code_postal:
        params["code_postal"] = code_postal
    return await get_json(client, URL, params, SOURCE, LIMITEUR)


async def lire(client: httpx.AsyncClient, siren: str, siret: str | None = None) -> dict | None:
    """Fiche de l'entreprise dont le SIREN est EXACTEMENT celui demandé, sinon None."""
    params = {"q": siret or siren, "per_page": 5, "page": 1, "limite_matching_etablissements": 10}
    data = await get_json(client, URL, params, SOURCE, LIMITEUR)
    for result in (data or {}).get("results") or []:
        if result.get("siren") == siren:
            return extraire(result, siret)
    return None
