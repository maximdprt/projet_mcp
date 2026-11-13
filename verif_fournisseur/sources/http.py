"""Outils communs à toutes les sources : appel HTTP prudent, nettoyage des textes, pannes.

Règles :
- une panne n'est jamais une réponse vide : elle lève SourceIndisponible ;
- un seul nouvel essai, uniquement sur erreur temporaire (429, 5xx, délai, réseau) ;
- tout texte venu de l'extérieur est nettoyé et tronqué : c'est une donnée, pas une instruction.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .. import config


class SourceIndisponible(Exception):
    """La source n'a pas répondu correctement. On ne conclut jamais à partir d'une panne."""

    def __init__(self, source: str, raison: str) -> None:
        super().__init__(f"{source} : {raison}")
        self.source = source
        self.raison = raison


class Limiteur:
    """Espace les appels pour rester sous la limite documentée d'une API."""

    def __init__(self, appels_par_seconde: float) -> None:
        self.intervalle = 1.0 / appels_par_seconde
        self._dernier = 0.0

    async def attendre(self) -> None:
        attente = self._dernier + self.intervalle - time.monotonic()
        if attente > 0:
            await asyncio.sleep(attente)
        self._dernier = time.monotonic()


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def texte(valeur: Any, maximum: int = 200) -> str | None:
    """Nettoie un texte externe : caractères de contrôle retirés, espaces réduits, longueur bornée."""
    if valeur is None:
        return None
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(valeur))
    s = re.sub(r"\s+", " ", s).strip()
    if "Ã" in s:  # texte UTF-8 mal décodé dans certaines annonces BODACC
        try:
            s = s.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
    if not s:
        return None
    return s if len(s) <= maximum else s[: maximum - 1] + "…"


async def get_json(client: httpx.AsyncClient, url: str, params: dict | None, source: str,
                   limiteur: Limiteur | None = None, timeout: float | None = None,
                   statuts_metier: tuple[int, ...] = ()) -> Any:
    """GET + JSON. `statuts_metier` : codes HTTP qui sont une vraie réponse (ex. 400 = numéro invalide)."""
    raison = "erreur inconnue"
    for tentative in range(2):
        if limiteur:
            await limiteur.attendre()
        try:
            r = await client.get(url, params=params, timeout=timeout or config.TIMEOUT_SECONDES)
        except httpx.TimeoutException:
            raison = "délai de réponse dépassé"
        except httpx.HTTPError as e:
            raison = f"erreur réseau ({type(e).__name__})"
        else:
            if r.status_code == 200 or r.status_code in statuts_metier:
                try:
                    return {"_http": r.status_code, **r.json()} if r.status_code != 200 else r.json()
                except ValueError:
                    raise SourceIndisponible(source, "réponse illisible (JSON invalide)") from None
            raison = f"HTTP {r.status_code}"
            if r.status_code not in (429, 500, 502, 503, 504):
                raise SourceIndisponible(source, raison)
        if tentative == 0:
            await asyncio.sleep(config.DELAI_NOUVEL_ESSAI)
    raise SourceIndisponible(source, raison)
