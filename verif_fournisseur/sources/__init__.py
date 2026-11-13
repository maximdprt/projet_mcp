"""Une source = un module = une API externe. Toutes ouvertes, sans clé.

| Module         | API                                         | Catalogue         |
|----------------|---------------------------------------------|-------------------|
| entreprises.py | Recherche d'entreprises (DINUM)             | data.gouv.fr      |
| bodacc.py      | BODACC (DILA)                               | data.gouv.fr      |
| adresse.py     | Géoplateforme – Géocodage (IGN)             | data.gouv.fr      |
| gels.py        | Gels des avoirs (DG Trésor)                 | data.gouv.fr      |
| tva.py         | VATComply (relais VIES)                     | public-apis       |
| change.py      | Frankfurter (taux BCE)                      | public-apis       |
"""

import httpx

from .. import config
from .http import SourceIndisponible, maintenant, texte  # noqa: F401


def creer_client() -> httpx.AsyncClient:
    """Client HTTP vers les API externes. En mode simulation, les API sont simulées (aucun réseau)."""
    transport = None
    if config.MODE == "simulation":
        from ..simulation import transport_simule
        transport = transport_simule()
    return httpx.AsyncClient(timeout=config.TIMEOUT_SECONDES, transport=transport,
                             headers={"User-Agent": config.USER_AGENT})
