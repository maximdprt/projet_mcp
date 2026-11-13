"""Branche ensemble, dans un seul processus : le MCP, les API simulées et le CRM (base temporaire).

Utilisé par la démo et par les tests : aucun serveur à lancer, aucun réseau, résultat reproductible.
"""

from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from crm import app as crm_app
from crm import db
from verif_fournisseur import config
from verif_fournisseur.simulation import transport_simule


def base_temporaire() -> str:
    chemin = str(Path(tempfile.mkdtemp()) / "crm_demo.sqlite3")
    db.CHEMIN = chemin
    db.initialiser(chemin)
    return chemin


@asynccontextmanager
async def clients(transport_externe: httpx.BaseTransport | None = None, cle: str | None = None):
    """(client des API externes, client du CRM avec la clé du MCP)."""
    config.MODE = "simulation"
    ext = httpx.AsyncClient(transport=transport_externe or transport_simule())
    crm = httpx.AsyncClient(transport=httpx.ASGITransport(app=crm_app.app), base_url="http://crm",
                            headers={"X-API-Key": cle or crm_app.CLE_MCP})
    async with ext, crm:
        yield ext, crm


@asynccontextmanager
async def client_admin():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=crm_app.app), base_url="http://crm",
                                 headers={"X-API-Key": crm_app.CLE_ADMIN}) as c:
        yield c
