"""Base SQLite du CRM de test."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

CHEMIN = os.getenv("CRM_DB_PATH", str(Path(__file__).with_name("crm.sqlite3")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS fournisseurs (
  id INTEGER PRIMARY KEY, nom TEXT NOT NULL, siret TEXT NOT NULL, tva TEXT, iban_reference TEXT NOT NULL,
  telephone_reference TEXT, adresse TEXT);
CREATE TABLE IF NOT EXISTS factures (
  id TEXT PRIMARY KEY, numero TEXT NOT NULL, fournisseur_id INTEGER REFERENCES fournisseurs(id),
  nom_emetteur TEXT, siret TEXT, tva TEXT, iban TEXT, adresse_emetteur TEXT, montant TEXT NOT NULL,
  devise TEXT NOT NULL DEFAULT 'EUR', montant_eur TEXT, date_emission TEXT, objet TEXT,
  statut TEXT NOT NULL DEFAULT 'recue', derniere_verification TEXT,
  source TEXT NOT NULL DEFAULT 'depot', scenario TEXT, fichier TEXT);
CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT, facture_id TEXT, horodatage TEXT NOT NULL, acteur TEXT NOT NULL,
  action TEXT NOT NULL, statut TEXT, detail TEXT);
"""

COLONNES_FACTURE = ("id", "numero", "fournisseur_id", "nom_emetteur", "siret", "tva", "iban", "adresse_emetteur",
                    "montant", "devise", "montant_eur", "date_emission", "objet", "statut")

# source d'une facture : historique (déjà payée), jeu_de_test (importée telle quelle), depot (fichier déposé)


def connexion(chemin: str | None = None) -> sqlite3.Connection:
    c = sqlite3.connect(chemin or CHEMIN, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def schema_a_jour(chemin: str | None = None) -> bool:
    """Faux si la base date d'une version antérieure (colonnes manquantes) : elle sera recréée."""
    try:
        with connexion(chemin) as c:
            colonnes = {r["name"] for r in c.execute("PRAGMA table_info(factures)")}
        return {"source", "scenario", "fichier"} <= colonnes
    except sqlite3.Error:
        return False


def _inserer(c: sqlite3.Connection, f: dict, source: str, scenario: str | None = None) -> None:
    c.execute(f"INSERT INTO factures ({','.join(COLONNES_FACTURE)}, source, scenario) VALUES "
              f"({','.join(':' + k for k in COLONNES_FACTURE)}, :source, :scenario)",
              {**f, "source": source, "scenario": scenario})


def initialiser(chemin: str | None = None, jeu_de_test: bool = True) -> None:
    """Recrée la base : référentiel fournisseurs + historique payé, et (si demandé) les 16 factures de test."""
    from .donnees_demo import FOURNISSEURS, HISTORIQUE, SCENARIOS
    with connexion(chemin) as c:
        c.executescript("DROP TABLE IF EXISTS journal; DROP TABLE IF EXISTS factures; "
                        "DROP TABLE IF EXISTS fournisseurs;" + SCHEMA)
        for f in FOURNISSEURS:
            c.execute("INSERT INTO fournisseurs VALUES (:id,:nom,:siret,:tva,:iban_reference,:telephone_reference,"
                      ":adresse)", f)
        for f in HISTORIQUE:
            _inserer(c, f, "historique")
        if jeu_de_test:
            for f, *_ in SCENARIOS:
                _inserer(c, f, "jeu_de_test", f["id"])
        c.execute("INSERT INTO journal (facture_id, horodatage, acteur, action, detail) VALUES (NULL,?,?,?,?)",
                  (maintenant(), "systeme", "initialisation",
                   json.dumps({"factures_a_traiter": len(SCENARIOS) if jeu_de_test else 0, "jeu_de_test": jeu_de_test})))


def ligne(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for cle in ("derniere_verification", "fichier"):
        if d.get(cle):
            try:
                d[cle] = json.loads(d[cle])
            except (TypeError, ValueError):
                pass
    if d.get("detail"):
        try:
            d["detail"] = json.loads(d["detail"])
        except (TypeError, ValueError):
            pass
    return d
