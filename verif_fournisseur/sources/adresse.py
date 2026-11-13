"""API Géoplateforme – Géocodage (IGN, data.gouv.fr ; remplace l'API Adresse).

Ouverte, sans clé, 50 appels/s. Sert à vérifier que l'adresse imprimée sur la facture existe
et qu'elle est dans la même commune (code INSEE) que l'établissement officiel.
"""

from __future__ import annotations

import httpx

from .http import get_json, texte

URL = "https://data.geopf.fr/geocodage/search"
SOURCE = "API Géoplateforme – Géocodage (IGN)"


async def geocoder(client: httpx.AsyncClient, adresse: str) -> dict | None:
    data = await get_json(client, URL, {"q": adresse, "limit": 1, "index": "address"}, SOURCE)
    features = (data or {}).get("features") or []
    if not features:
        return None
    p = features[0].get("properties") or {}
    return {
        "adresse_reconnue": texte(p.get("label")),
        "score": round(float(p.get("score") or 0), 2),
        "code_postal": p.get("postcode"),
        "commune_insee": p.get("citycode"),
        "commune": texte(p.get("city"), 80),
    }
