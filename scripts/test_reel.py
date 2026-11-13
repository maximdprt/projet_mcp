"""Test sur les VRAIES API publiques (connexion internet nécessaire). À lancer avant l'oral.

    python scripts/test_reel.py
    python scripts/test_reel.py 55203253400646 "DANONE"   # en plus : un SIRET et un nom de votre choix

Chaque scénario affiche le statut, les alertes, et le résultat de chacun des 8 contrôles.
Si une ligne affiche INDISPONIBLE, l'API correspondante ne répond pas (ou son format a changé) :
voir le module correspondant dans verif_fournisseur/sources/.
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from verif_fournisseur import config  # noqa: E402

config.MODE = "reel"

from verif_fournisseur import sources, verifications as v  # noqa: E402

SCENARIOS = [
    ("SIRET inventé (refusé sans appel réseau)", dict(siret="13002526500014", nom_sur_facture="DINUM")),
    ("Vrai fournisseur, toutes les infos justes", dict(
        siret="13002526500013", nom_sur_facture="DINUM", tva_facture="FR07130025265",
        adresse_facture="20 avenue de Ségur 75007 Paris", montant="2900", devise="EUR")),
    ("Vrai SIRET, nom d'un autre (doit bloquer)", dict(siret="13002526500013", nom_sur_facture="SOLUTIONS DURAND")),
    ("TVA d'une autre entreprise (doit bloquer)", dict(siret="13002526500013", nom_sur_facture="DINUM",
                                                       tva_facture="FR40303265045")),
    ("Facture en dollars (conversion BCE)", dict(siret="13002526500013", nom_sur_facture="DINUM", montant="4500",
                                                 devise="USD")),
    ("Adresse dans une autre ville", dict(siret="13002526500013", nom_sur_facture="DINUM",
                                          adresse_facture="1 place Bellecour 69002 Lyon")),
]


def afficher(titre: str, r: dict) -> None:
    print(f"\n=== {titre} ===")
    if r.get("refus"):
        print("REFUS :", r["motif"])
        return
    print("STATUT :", r["statut"], "| alertes :", [a["code"] for a in r["alertes"]] or "aucune")
    for c in r["controles"]:
        print(f"  - {c['controle']:<20} {c['resultat']:<12} {c.get('raison', '')}")
    if r.get("montant_eur"):
        print("  montant en euros :", r["montant_eur"])


async def main() -> None:
    async with sources.creer_client() as c:
        for titre, kw in SCENARIOS:
            afficher(titre, await v.verifier_fournisseur(c, **kw))
        print("\n=== Recherche par nom ===")
        r = await v.rechercher_entreprise(c, "boulangerie", "75011")
        print(r.get("nombre_total_resultats"), "résultats ->", r.get("consigne") or r)
        if len(sys.argv) > 2:
            afficher(f"SIRET au choix : {sys.argv[1]}", await v.verifier_fournisseur(c, sys.argv[1], sys.argv[2]))


if __name__ == "__main__":
    asyncio.run(main())
