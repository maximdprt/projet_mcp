"""Outil 1 — rechercher_entreprise : « je n'ai qu'un nom ».

Cherche dans le registre officiel (Recherche d'entreprises, DINUM). Au plus 5 candidats, sans dirigeants.
Ne choisit jamais entre homonymes : pour vérifier, il faut le SIRET imprimé sur la facture. Lecture seule.
"""

from __future__ import annotations

import re

import httpx

from .. import config
from ..sources import entreprises
from ..sources.http import SourceIndisponible, maintenant
from .commun import refus


async def rechercher_entreprise(client: httpx.AsyncClient, nom: str, code_postal: str | None = None) -> dict:
    nom = (nom or "").strip()
    if re.fullmatch(r"[\d\s]{9,17}", nom):
        return refus("C'est un numéro, pas un nom : utiliser verifier_fournisseur avec ce SIRET.")
    if not 3 <= len(nom) <= 100:
        return refus("Le nom recherché doit contenir entre 3 et 100 caractères.")
    if code_postal and not re.fullmatch(r"\d{5}", code_postal.strip()):
        return refus("Le code postal doit contenir 5 chiffres.")
    try:
        data = await entreprises.chercher_par_nom(client, nom, code_postal.strip() if code_postal else None)
    except SourceIndisponible as e:
        return {"erreur": "SOURCE_INDISPONIBLE", "source": e.source, "raison": e.raison,
                "consigne": "Aucune conclusion possible : réessayer plus tard."}
    candidats = []
    for r in (data or {}).get("results") or []:
        f = entreprises.extraire(r)
        candidats.append({k: f[k] for k in ("siren", "nom_officiel", "sigle", "etat_administratif",
                                            "date_creation", "siege")})
    total = (data or {}).get("total_results", len(candidats))
    if not candidats:
        consigne = ("Aucune entreprise trouvée dans la base publique. Cela ne prouve PAS qu'elle n'existe pas. "
                    "Demander le SIRET imprimé sur la facture.")
    elif total > 1:
        consigne = ("Plusieurs entreprises correspondent : ne pas choisir à la place de l'utilisateur. Demander le "
                    "SIRET imprimé sur la facture, puis appeler verifier_fournisseur.")
    else:
        consigne = "Un seul résultat, mais un nom ne suffit pas : confirmer avec le SIRET imprimé sur la facture."
    return {"mode": config.MODE, "recherche": nom, "nombre_total_resultats": total, "candidats": candidats,
            "consigne": consigne, "source": entreprises.SOURCE, "consulte_le": maintenant()}
