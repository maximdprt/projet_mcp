"""Démo : les 16 factures du CRM traitées SANS puis AVEC le MCP.

    python -m demo.comparaison          -> affiche le tableau et écrit RAPPORT_DEMO.md

« Sans MCP » = ce que fait un assistant ou une automatisation qui lit la facture et la paie :
il fait confiance au document (nom, IBAN, montant). C'est une règle simulée, pas un vrai modèle.
« Avec MCP » = l'outil traiter_factures_crm, exécuté pour de vrai sur le CRM de test.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

from crm.donnees_demo import SCENARIOS
from demo.harnais import base_temporaire, client_admin, clients
from verif_fournisseur import verifications
from verif_fournisseur.simulation import TAUX_BCE

RACINE = Path(__file__).resolve().parents[1]
LIBELLES = {"verifiee": "✅ vérifiée", "a_verifier_humain": "🟠 contrôle humain", "bloquee": "⛔ bloquée",
            "impossible_de_verifier": "🟣 impossible"}


def _eur(f: dict) -> Decimal:
    m = Decimal(f["montant"])
    return (m * Decimal(TAUX_BCE[f["devise"]])).quantize(Decimal("0.01")) if f["devise"] != "EUR" else m


async def executer() -> dict:
    base_temporaire()
    async with clients() as (ext, crm):
        resultat = await verifications.traiter_factures_crm(ext, crm)
        # Le MCP tente-t-il de payer ? Il n'a pas d'outil pour ça, et sa clé est refusée par le CRM :
        refus_mcp = (await crm.post("/api/factures/F01/paiement")).status_code
    async with client_admin() as adm:
        paiement_bloquee = (await adm.post("/api/factures/F02/paiement")).status_code
        paiement_verifiee = (await adm.post("/api/factures/F01/paiement")).status_code

    par_id = {x["facture_id"]: x for x in resultat["factures"]}
    lignes, expose, protege, conformes = [], Decimal(0), Decimal(0), 0
    for facture, piege, attendu, codes in SCENARIOS:
        r = par_id[facture["id"]]
        statut_crm = {"BLOQUER_LE_PAIEMENT": "bloquee", "VERIFICATION_HUMAINE_REQUISE": "a_verifier_humain",
                      "AUCUNE_ALERTE_DETECTEE": "verifiee", "IMPOSSIBLE_DE_VERIFIER": "impossible_de_verifier"}[r["statut"]]
        eur = _eur(facture)
        if attendu != "verifiee":
            expose += eur
            if statut_crm != "verifiee":
                protege += eur
        conformes += statut_crm == attendu and set(codes) <= set(r["codes_alertes"])
        lignes.append((facture["id"], piege, f"{eur:,.2f} €".replace(",", " "), "💸 payée", LIBELLES[statut_crm],
                       ", ".join(c for c in r["codes_alertes"]) or "—"))
    return {"lignes": lignes, "expose": expose, "protege": protege, "conformes": conformes, "total": len(SCENARIOS),
            "refus_mcp": refus_mcp, "paiement_bloquee": paiement_bloquee, "paiement_verifiee": paiement_verifiee,
            "synthese": resultat["synthese"]}


def rapport_markdown(r: dict) -> str:
    t = ["# Démo : 16 factures, sans puis avec le MCP Vérif Fournisseur", "",
         "Mode **simulation** : API simulées, entreprises fictives, résultat reproductible.", "",
         "| Facture | Piège | Montant | Sans MCP | Avec MCP | Alertes du MCP |", "|---|---|---|---|---|---|"]
    t += [f"| {a} | {b} | {c} | {d} | {e} | `{f}` |" for a, b, c, d, e, f in r["lignes"]]
    fmt = lambda d: f"{d:,.2f} €".replace(",", " ")  # noqa: E731
    t += ["", "## Bilan", "",
          f"- **Sans MCP** : 16 factures payées, dont **{fmt(r['expose'])}** sur des factures frauduleuses ou anormales.",
          f"- **Avec MCP** : {fmt(r['protege'])} retenus sur {fmt(r['expose'])} exposés ; seules les factures saines "
          "passent en « vérifiée ».",
          f"- Résultat conforme à l'attendu pour **{r['conformes']}/{r['total']}** scénarios.",
          f"- Synthèse des statuts : `{r['synthese']}`",
          f"- Le MCP essaie de payer avec sa clé → HTTP **{r['refus_mcp']}** (refusé par le CRM).",
          f"- Un humain essaie de payer une facture bloquée → HTTP **{r['paiement_bloquee']}** (refusé).",
          f"- Un humain paie une facture vérifiée → HTTP **{r['paiement_verifiee']}** (accepté).", ""]
    return "\n".join(t)


def main() -> None:
    r = asyncio.run(executer())
    md = rapport_markdown(r)
    (RACINE / "RAPPORT_DEMO.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
