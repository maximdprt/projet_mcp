"""Fausses API pour tester les garde-fous : les 6 API sont simulées, et chaque test peut provoquer
une panne (délai, HTTP 500, JSON illisible) ou une réponse piégée sur n'importe laquelle."""

import asyncio
from collections import Counter

import httpx
import pytest

from verif_fournisseur import config
from verif_fournisseur.simulation import gestionnaire
from verif_fournisseur.sources import entreprises, gels

RE = "recherche-entreprises.api.gouv.fr"
BO = "bodacc-datadila.opendatasoft.com"
GEO = "data.geopf.fr"
GELS = "gels-avoirs.dgtresor.gouv.fr"
TVA = "api.vatcomply.com"
FX = "api.frankfurter.dev"

# Fournisseur fictif sain (mode simulation)
SIRET = "90123456700013"
NOM = "ATELIER MERCIER"
TVA_OK = "FR15901234567"
IBAN_OK = "FR7630004000031234567890143"
ADRESSE_OK = "45 cours Gambetta 69003 Lyon"


@pytest.fixture(autouse=True)
def reglages():
    config.DELAI_NOUVEL_ESSAI = 0
    config.MODE = "simulation"
    entreprises.LIMITEUR.intervalle = 0
    gels.vider_cache()


class FausseAPI:
    def __init__(self):
        self.pannes: dict = {}        # hôte -> "timeout" | "json" | code HTTP
        self.surcharges: dict = {}    # hôte -> fonction(params) -> JSON
        self.appels = Counter()
        self.params: dict = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        h = request.url.host
        self.appels[h] += 1
        self.params[h] = dict(request.url.params)
        panne = self.pannes.get(h)
        if panne == "timeout":
            raise httpx.ReadTimeout("délai dépassé")
        if panne == "json":
            return httpx.Response(200, text="<html>maintenance</html>")
        if isinstance(panne, int):
            return httpx.Response(panne, json={"erreur": "panne"})
        if h in self.surcharges:
            return httpx.Response(200, json=self.surcharges[h](dict(request.url.params)))
        return gestionnaire(request)

    def transport(self):
        return httpx.MockTransport(self.handler)

    def appeler(self, fonction, *args, **kwargs):
        async def _run():
            async with httpx.AsyncClient(transport=self.transport()) as c:
                return await fonction(c, *args, **kwargs)
        return asyncio.run(_run())


@pytest.fixture
def api():
    return FausseAPI()
