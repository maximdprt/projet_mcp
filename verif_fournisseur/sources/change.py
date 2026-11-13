"""Frankfurter (liste public-apis) : taux de référence de la Banque centrale européenne.

Ouverte, sans clé. Sert à convertir en euros une facture en devise, pour appliquer les seuils.
Le calcul est fait en Decimal par le serveur, arrondi au centime : l'IA ne calcule jamais.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import httpx

from .http import SourceIndisponible, get_json

URL = "https://api.frankfurter.dev/v1/latest"
SOURCE = "Frankfurter (taux de référence BCE)"


async def convertir_en_euros(client: httpx.AsyncClient, montant: Decimal, devise: str) -> dict:
    if devise == "EUR":
        return {"montant_eur": str(montant), "taux": "1", "date_taux": None, "devise": "EUR"}
    data = await get_json(client, URL, {"base": devise, "symbols": "EUR"}, SOURCE)
    taux = ((data or {}).get("rates") or {}).get("EUR")
    if taux is None:
        raise SourceIndisponible(SOURCE, f"aucun taux BCE pour la devise {devise}")
    t = Decimal(str(taux))
    return {"montant_eur": str((montant * t).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "taux": str(t), "date_taux": data.get("date"), "devise": devise}
