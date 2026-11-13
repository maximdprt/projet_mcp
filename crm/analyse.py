"""Le CRM fait analyser une facture par le serveur MCP, exactement comme le ferait une IA.

Il lance `python -m verif_fournisseur.server` (transport stdio, protocole MCP) et appelle l'outil
`traiter_factures_crm`. C'est le serveur MCP qui lit la facture dans le CRM (clé MCP), interroge les sources,
applique les règles et écrit le verdict. Le CRM ne décide rien : il déclenche l'appel et en garde la trace.

`executeur` est remplaçable (tests : appel en mémoire, sans sous-processus).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
OUTIL = "traiter_factures_crm"
DELAI_SECONDES = 120


async def _appel_stdio(arguments: dict) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "verif_fournisseur.server"], cwd=str(RACINE),
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(RACINE)})
    async with stdio_client(params) as (lecture, ecriture):
        async with ClientSession(lecture, ecriture) as session:
            await session.initialize()
            resultat = await session.call_tool(OUTIL, arguments)
    if getattr(resultat, "structured_content", None):
        return dict(resultat.structured_content)
    texte = resultat.content[0].text if resultat.content else "{}"
    try:
        return json.loads(texte)
    except ValueError:
        return {"erreur": "REPONSE_ILLISIBLE", "raison": texte[:200]}


def _executer_dans_un_fil(arguments: dict) -> dict:
    # boucle d'événements dédiée : les sous-processus asyncio fonctionnent aussi sous Windows
    return asyncio.run(asyncio.wait_for(_appel_stdio(arguments), DELAI_SECONDES))


async def appeler_mcp(arguments: dict) -> dict:
    """Appelle l'outil traiter_factures_crm du serveur MCP ; renvoie sa réponse (dict)."""
    return await asyncio.to_thread(_executer_dans_un_fil, arguments)


executeur = appeler_mcp
