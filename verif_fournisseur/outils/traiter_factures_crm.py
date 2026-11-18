"""Outil 3 — traiter_factures_crm : « vérifie les factures du CRM ».

Lit la facture dans le CRM, lance les 8 contrôles de verifier_fournisseur, ajoute le 9e (référentiel du CRM :
IBAN ou SIRET différent, doublon, montant anormal, fournisseur inconnu) puis écrit le verdict dans le CRM.
Seule écriture : le résultat et une trace d'audit. Ne paie jamais, ne modifie jamais un IBAN.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import httpx

from .. import config, crm_client
from ..regles import A_VERIFIER, INFO, MESSAGES, STATUT_CRM, alerte, regles_crm, statut_final
from ..sources.http import SourceIndisponible, texte
from .commun import empreinte, refus, resume_controles
from .verifier_fournisseur import verifier_fournisseur


async def _traiter_une(ext: httpx.AsyncClient, crm: httpx.AsyncClient, facture_id: str,
                       aujourd_hui: date | None) -> dict:
    f = await crm_client.facture(crm, facture_id)
    if f is None:
        return refus(f"Facture {facture_id} introuvable dans le CRM.")
    if f.get("statut") == "payee":
        return refus(f"Facture {facture_id} déjà payée : aucune modification.", facture_id=facture_id)
    fournisseur = await crm_client.fournisseur(crm, f["fournisseur_id"]) if f.get("fournisseur_id") else None
    historique = await crm_client.historique(crm, f["fournisseur_id"]) if fournisseur else []

    rapport = await verifier_fournisseur(ext, f.get("siret") or "", f.get("nom_emetteur") or "", f.get("iban"),
                                         f.get("tva"), f.get("adresse_emetteur"), f.get("montant"),
                                         f.get("devise") or "EUR", aujourd_hui)
    if rapport.get("refus"):  # facture incomplète : jamais « vérifiée »
        rapport = {"alertes": [alerte(A_VERIFIER, "FACTURE_INCOMPLETE", rapport["motif"])],
                   "sources_indisponibles": [], "controles": []}
    m_eur = Decimal(rapport["montant_eur"]) if rapport.get("montant_eur") else None
    al_crm = regles_crm(f, fournisseur, historique, m_eur)
    alertes = rapport["alertes"] + al_crm
    statut = statut_final(alertes, rapport["sources_indisponibles"])
    rapport.update(statut=statut, message=MESSAGES[statut], alertes=alertes)
    rapport.setdefault("controles", []).append({"controle": "referentiel_crm", "source": "CRM",
                                                "resultat": "ALERTE" if any(a["niveau"] != INFO for a in al_crm)
                                                else "OK"})
    trace = await crm_client.enregistrer_verification(crm, facture_id, {
        "statut": STATUT_CRM[statut], "statut_mcp": statut, "montant_eur": rapport.get("montant_eur"),
        "alertes": alertes, "controles": resume_controles(rapport["controles"]), "message": MESSAGES[statut],
        "empreinte": empreinte(rapport), "mode": config.MODE})
    return {"facture_id": facture_id, "numero": f.get("numero"), "nom_emetteur": texte(f.get("nom_emetteur"), 120),
            "montant": f.get("montant"), "devise": f.get("devise"), "statut": statut, "statut_crm": STATUT_CRM[statut],
            "message": MESSAGES[statut], "alertes": alertes, "controles": rapport["controles"],
            "sources_indisponibles": rapport["sources_indisponibles"], "journal_crm": trace, "mode": config.MODE}


async def traiter_factures_crm(ext: httpx.AsyncClient, crm: httpx.AsyncClient, facture_id: str | None = None,
                               aujourd_hui: date | None = None) -> dict:
    try:
        if facture_id:
            if not re.fullmatch(r"[A-Za-z0-9-]{3,30}", facture_id.strip()):
                return refus("Identifiant de facture invalide (lettres, chiffres et tirets, 3 à 30 caractères).")
            return await _traiter_une(ext, crm, facture_id.strip(), aujourd_hui)
        a_traiter = (await crm_client.factures(crm, "recue"))[:25]
        resultats = [await _traiter_une(ext, crm, x["id"], aujourd_hui) for x in a_traiter]
    except SourceIndisponible as e:
        return {"erreur": "SOURCE_INDISPONIBLE", "source": e.source, "raison": e.raison,
                "consigne": "Rien n'a été modifié dans le CRM. Réessayer quand il répond."}
    synthese: dict[str, int] = {}
    for x in resultats:
        synthese[x.get("statut", "REFUS")] = synthese.get(x.get("statut", "REFUS"), 0) + 1
    return {"mode": config.MODE, "nombre_traitees": len(resultats), "synthese": synthese,
            "factures": [{k: x.get(k) for k in ("facture_id", "numero", "nom_emetteur", "montant", "devise",
                                                 "statut", "message")} | {"codes_alertes": [a["code"] for a in
                                                                                         x.get("alertes", [])]}
                         for x in resultats],
            "consigne": "Aucune facture n'a été payée : le paiement reste une action humaine dans le CRM."}
