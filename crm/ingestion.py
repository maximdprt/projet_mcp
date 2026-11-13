"""Enregistrement d'une facture déposée : identifiant, rattachement au référentiel, lien avec le jeu de test.

Ce n'est pas une règle de décision (celles-ci restent dans verif_fournisseur/regles.py) : c'est le travail d'un
logiciel de comptabilité fournisseurs, qui rattache une facture à un fournisseur connu avant tout contrôle.
- Rattachement : nom identique (normalisé) d'abord, sinon SIRET identique, sinon aucun (« fournisseur inconnu »).
  Le nom d'abord : une facture au nom d'un fournisseur connu mais avec un autre SIRET doit être comparée à ce
  fournisseur (usurpation), pas à la société dont on a recopié le SIRET.
"""

from __future__ import annotations

import re
import sqlite3

from .extraction import normaliser_nom


def rattacher(c: sqlite3.Connection, nom: str | None, siret: str | None) -> tuple[int | None, str | None]:
    """(id du fournisseur, mode de rattachement : « nom », « siret » ou None)."""
    cible = normaliser_nom(nom)
    if cible:
        for r in c.execute("SELECT id, nom FROM fournisseurs"):
            if normaliser_nom(r["nom"]) == cible:
                return r["id"], "nom"
    chiffres = re.sub(r"\D", "", str(siret or ""))
    if chiffres:
        r = c.execute("SELECT id FROM fournisseurs WHERE siret=?", (chiffres,)).fetchone()
        if r:
            return r["id"], "siret"
    return None, None


def scenario_correspondant(numero: str, nom: str | None) -> str | None:
    """La facture déposée est-elle une facture du jeu de test (même numéro, même émetteur) ?"""
    from .donnees_demo import SCENARIOS
    for f, *_ in SCENARIOS:
        if f["numero"] == numero and normaliser_nom(f.get("nom_emetteur")) == normaliser_nom(nom):
            return f["id"]
    return None


def nouvel_identifiant(c: sqlite3.Connection) -> str:
    n = c.execute("SELECT COUNT(*) FROM factures WHERE source='depot'").fetchone()[0] + 1
    while c.execute("SELECT 1 FROM factures WHERE id=?", (f"D{n:04d}",)).fetchone():
        n += 1
    return f"D{n:04d}"
