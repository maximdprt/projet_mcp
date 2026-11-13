"""VATComply (liste public-apis) : validité d'un numéro de TVA intracommunautaire dans VIES.

Ouverte, sans clé. Relaie le service officiel VIES de la Commission européenne.
Le calcul local dit si le numéro est bien formé ; VIES dit s'il est réellement enregistré.
"""

from __future__ import annotations

import httpx

from .http import SourceIndisponible, get_json, texte

URL = "https://api.vatcomply.com/vat"
SOURCE = "VATComply (relais du service VIES, Commission européenne)"


async def verifier(client: httpx.AsyncClient, numero: str) -> dict:
    data = await get_json(client, URL, {"vat_number": numero}, SOURCE, statuts_metier=(400,))
    if isinstance(data, dict) and data.get("_http") == 400:
        if data.get("detail") and data["detail"] != "INVALID_INPUT":
            raise SourceIndisponible(SOURCE, f"VIES indisponible ({data['detail']})")
        return {"enregistre_vies": False, "raison": texte(data.get("error") or data.get("detail"))}
    if not isinstance(data, dict) or "valid" not in data:
        raise SourceIndisponible(SOURCE, "réponse inattendue (pas de champ 'valid')")
    return {"enregistre_vies": bool(data["valid"]), "nom_vies": texte(data.get("name"), 120),
            "pays": data.get("country_code")}
