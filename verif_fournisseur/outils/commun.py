"""Briques communes aux 3 outils : refus motivé, rapport de contrôles, empreinte et résumé pour le CRM.

Chaque rapport liste TOUS les contrôles, toujours dans le même ordre, avec leur source et leur résultat :
OK, ALERTE, INDISPONIBLE ou NON_DEMANDE. Rien n'est laissé à l'interprétation de l'IA.
"""

from __future__ import annotations

import hashlib
import json

from .. import config
from ..regles import A_VERIFIER, INFO, MESSAGES, RAPPELS, alerte, statut_final
from ..sources.http import SourceIndisponible, maintenant, texte


def refus(motif: str, **extra) -> dict:
    return {"refus": True, "motif": motif, **extra}


class Rapport:
    """Accumule contrôles, alertes et pannes, puis conclut avec un statut décidé par les règles."""

    def __init__(self, **entete) -> None:
        self.entete = {"mode": config.MODE, **entete}
        self.controles: list[dict] = []
        self.alertes: list[dict] = []
        self.pannes: list[str] = []
        self.sources: list[dict] = []
        self.donnees: dict = {}

    def controle(self, nom: str, source: str, alertes: list[dict] | None = None, detail=None,
                 indisponible: str | None = None, non_demande: bool = False) -> None:
        alertes = alertes or []
        self.alertes += alertes
        if indisponible:
            resultat = "INDISPONIBLE"
        elif non_demande:
            resultat = "NON_DEMANDE"
        else:
            resultat = "ALERTE" if any(a["niveau"] != INFO for a in alertes) else "OK"
            if source != "calcul local":
                self.sources.append({"nom": source, "consulte_le": maintenant()})
        self.controles.append({"controle": nom, "source": source, "resultat": resultat,
                               **({"raison": indisponible} if indisponible else {}),
                               **({"detail": detail} if detail is not None else {})})

    def panne(self, nom: str, e: SourceIndisponible, essentielle: bool, code: str = "") -> None:
        if essentielle:
            self.pannes.append(f"{e.source} : {e.raison}")
            self.controle(nom, e.source, indisponible=e.raison)
        else:
            self.controle(nom, e.source, [alerte(A_VERIFIER, code, f"{e.source} indisponible : contrôle à "
                                                 "refaire manuellement.")], indisponible=e.raison)

    def conclure(self) -> dict:
        statut = statut_final(self.alertes, self.pannes)
        return {"statut": statut, "message": MESSAGES[statut], **self.entete, "alertes": self.alertes,
                "controles": self.controles, **self.donnees, "sources_consultees": self.sources,
                "sources_indisponibles": self.pannes, "rappels": RAPPELS}




def empreinte(rapport: dict) -> str:
    return hashlib.sha256(json.dumps(rapport, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def resume_controles(controles: list[dict]) -> list[dict]:
    """Ce que le CRM garde de chaque contrôle : nom, source, résultat, raison d'une panne. Jamais le détail
    (données d'entreprise, annonces…) : le CRM n'en a pas besoin pour afficher la décision."""
    limites = {"controle": 40, "source": 120, "raison": 200}
    return [{"resultat": c["resultat"], **{k: texte(c[k], n) for k, n in limites.items() if c.get(k)}}
            for c in controles[:20]]
