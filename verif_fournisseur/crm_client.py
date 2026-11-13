"""Client du CRM. La clé (CRM_CLE_MCP) vient du .env du serveur : l'IA ne la voit jamais.

Cette clé n'a qu'un droit d'écriture : enregistrer le RÉSULTAT d'une vérification.
Le CRM refuse avec elle tout paiement, toute validation humaine et toute modification d'IBAN.
"""

from __future__ import annotations

import httpx

from . import config
from .sources.http import SourceIndisponible

SOURCE = "CRM"


def creer_client_crm() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=config.CRM_URL, timeout=config.TIMEOUT_SECONDES,
                             headers={"X-API-Key": config.CRM_CLE_MCP})


async def _appel(client: httpx.AsyncClient, methode: str, chemin: str, **kw) -> dict | list | None:
    try:
        r = await client.request(methode, chemin, **kw)
    except httpx.HTTPError as e:
        raise SourceIndisponible(SOURCE, f"CRM injoignable ({type(e).__name__})") from None
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise SourceIndisponible(SOURCE, f"HTTP {r.status_code} : {r.text[:150]}")
    return r.json()


async def facture(client, facture_id: str) -> dict | None:
    return await _appel(client, "GET", f"/api/factures/{facture_id}")


async def factures(client, statut: str) -> list[dict]:
    return await _appel(client, "GET", "/api/factures", params={"statut": statut}) or []


async def fournisseur(client, fournisseur_id: int) -> dict | None:
    return await _appel(client, "GET", f"/api/fournisseurs/{fournisseur_id}")


async def historique(client, fournisseur_id: int) -> list[dict]:
    return await _appel(client, "GET", f"/api/fournisseurs/{fournisseur_id}/factures") or []


async def enregistrer_verification(client, facture_id: str, contenu: dict) -> dict:
    return await _appel(client, "POST", f"/api/factures/{facture_id}/verification", json=contenu)
