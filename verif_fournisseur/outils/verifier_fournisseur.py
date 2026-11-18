"""Outil 2 — verifier_fournisseur : « j'ai une facture devant moi ».

8 contrôles, toujours dans cet ordre : identifiants (calcul local) → l'entreprise existe → le nom correspond →
procédures BODACC → gel des avoirs → TVA (VIES) → adresse (IGN) → montant en euros (BCE).
Un SIRET à clé fausse est refusé avant tout appel réseau. Le statut est décidé par regles.statut_final.
Lecture seule.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import httpx

from .. import config
from ..identifiants import controler_iban, controler_siret, controler_tva
from ..regles import (A_VERIFIER, BLOQUANT, alerte, alertes_procedures, analyser_procedures, anciennete_jours,
                      comparer_noms, parser_montant)
from ..sources import adresse, bodacc, change, entreprises, gels, tva
from ..sources.http import SourceIndisponible, texte
from .commun import Rapport, refus


async def verifier_fournisseur(client: httpx.AsyncClient, siret: str, nom_sur_facture: str,
                               iban: str | None = None, tva_facture: str | None = None,
                               adresse_facture: str | None = None, montant: object = None,
                               devise: str = "EUR", aujourd_hui: date | None = None) -> dict:
    nom_sur_facture = texte(nom_sur_facture, 200) or ""
    if len(nom_sur_facture) < 2:
        return refus("Indiquer le nom du fournisseur tel qu'il est écrit sur la facture.")
    if not siret:
        return refus("Le SIRET imprimé sur la facture est obligatoire : un nom seul ne suffit pas (homonymes). "
                      "Ne jamais deviner ni inventer un SIRET.")
    devise = (devise or "EUR").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", devise):
        return refus("La devise doit être un code ISO à 3 lettres (EUR, USD, GBP…).")
    montant_dec = None
    if montant not in (None, ""):
        try:
            montant_dec = parser_montant(montant)
        except ValueError as e:
            return refus(str(e))

    r = Rapport(nom_sur_facture=nom_sur_facture)

    # 1. Identifiants (calcul local) : un SIRET faux arrête tout, sans appel réseau.
    c_siret = controler_siret(siret)
    c_iban = controler_iban(iban) if iban else None
    c_tva = None
    al = []
    if not c_siret["valide"]:
        r.controle("identifiants", "calcul local", [alerte(BLOQUANT, "SIRET_INVALIDE", c_siret["raison"])],
                   detail={"siret": c_siret})
        return r.conclure()
    siret = c_siret["valeur"]
    siren = siret[:9]
    if c_iban:
        if not c_iban["valide"]:
            al.append(alerte(BLOQUANT, "IBAN_INVALIDE", c_iban["raison"]))
        elif not c_iban.get("est_francais"):
            al.append(alerte(A_VERIFIER, "IBAN_ETRANGER", f"IBAN domicilié hors de France ({c_iban['pays']}) : "
                             "signal fréquent de fraude au changement de RIB. Confirmer par contre-appel."))
    if tva_facture:
        c_tva = controler_tva(tva_facture, siren)
        if not c_tva["valide"]:
            al.append(alerte(BLOQUANT if c_tva.get("verifiable", True) else A_VERIFIER, "TVA_INCOHERENTE",
                             c_tva["raison"]))
    r.controle("identifiants", "calcul local", al, detail={k: v for k, v in
                                                           (("siret", c_siret), ("iban", c_iban), ("tva", c_tva)) if v})

    # 2. Identité et état de l'entreprise (essentiel).
    fiche = None
    try:
        fiche = await entreprises.lire(client, siren, siret)
    except SourceIndisponible as e:
        r.panne("identite_entreprise", e, essentielle=True)
    else:
        al = []
        if fiche is None:
            al.append(alerte(A_VERIFIER, "ENTREPRISE_NON_TROUVEE", "Aucune entreprise avec ce SIREN dans la base "
                             "publique (non diffusible ou inexistante) : vérification manuelle obligatoire."))
        else:
            if fiche["etat_administratif"] != "active":
                al.append(alerte(BLOQUANT, "ENTREPRISE_CESSEE", "L'entreprise est cessée (fermeture : "
                                 f"{fiche.get('date_fermeture') or 'date non précisée'})."))
            etab = fiche.get("etablissement_demande")
            if etab is None:
                al.append(alerte(A_VERIFIER, "ETABLISSEMENT_NON_RETROUVE", "Ce SIRET précis n'a pas été retrouvé "
                                 "parmi les établissements de l'entreprise."))
            elif etab["etat"] != "ouvert":
                al.append(alerte(BLOQUANT, "ETABLISSEMENT_FERME", f"L'établissement {siret} est fermé "
                                 f"(depuis {etab.get('date_fermeture') or 'date inconnue'})."))
            age = anciennete_jours(fiche.get("date_creation"), aujourd_hui)
            if age is not None and age < config.JOURS_ENTREPRISE_RECENTE:
                al.append(alerte(A_VERIFIER, "ENTREPRISE_RECENTE", f"Entreprise créée il y a {age} jours "
                                 f"(seuil : {config.JOURS_ENTREPRISE_RECENTE})."))
        r.controle("identite_entreprise", entreprises.SOURCE, al, detail=fiche and {
            k: fiche.get(k) for k in ("siren", "nom_officiel", "sigle", "etat_administratif", "date_creation",
                                      "date_fermeture", "etablissement_demande", "siege", "lien_fiche_publique")})

        # 3. Nom de la facture contre nom officiel (calcul local sur données officielles).
        if fiche:
            noms = [fiche.get("nom_officiel"), fiche.get("nom_complet"), fiche.get("sigle"), *fiche["enseignes"]]
            comp = comparer_noms(nom_sur_facture, [n for n in noms if n])
            al = []
            if not fiche.get("diffusion_complete"):
                al.append(alerte(A_VERIFIER, "DIFFUSION_PARTIELLE", "Données partiellement diffusées : le nom ne "
                                 "peut pas être comparé de façon sûre."))
            elif comp["correspondance"] == "different":
                al.append(alerte(BLOQUANT, "NOM_DIFFERENT", f"Le nom sur la facture (« {nom_sur_facture} ») ne "
                                 f"correspond pas au nom officiel de ce SIRET (« {fiche.get('nom_officiel')} »)."))
            elif comp["correspondance"] == "proche":
                al.append(alerte(A_VERIFIER, "NOM_APPROCHANT", "Le nom sur la facture ressemble au nom officiel "
                                 f"(« {comp['nom_officiel_le_plus_proche']} ») sans être identique : possible "
                                 "imitation."))
            r.controle("nom_facture", "calcul local", al, detail=comp)

    # 4. Procédures collectives et radiations (essentiel).
    try:
        annonces = await bodacc.lire(client, siren)
    except SourceIndisponible as e:
        r.panne("procedures_bodacc", e, essentielle=True)
    else:
        analyse = analyser_procedures(annonces)
        r.controle("procedures_bodacc", bodacc.SOURCE, alertes_procedures(analyse),
                   detail={"analyse": analyse, "annonces_recentes": annonces[:5]})

    # 5. Gel des avoirs (essentiel : payer une entité sanctionnée est interdit).
    noms_a_filtrer = [nom_sur_facture] + ([fiche.get("nom_officiel"), fiche.get("nom_complet")] if fiche else [])
    try:
        res = await gels.rechercher(client, [n for n in noms_a_filtrer if n],
                                    inclure_personnes=bool(fiche and fiche.get("est_entrepreneur_individuel")))
    except SourceIndisponible as e:
        r.panne("gel_des_avoirs", e, essentielle=True)
    else:
        al = []
        if res["correspondances_exactes"]:
            al.append(alerte(BLOQUANT, "GEL_DES_AVOIRS", "Le fournisseur correspond à une entrée du registre national "
                             "des gels des avoirs : mise à disposition de fonds interdite. À confirmer par le "
                             "responsable conformité."))
        elif res["correspondances_partielles"]:
            al.append(alerte(A_VERIFIER, "GEL_DES_AVOIRS_PARTIEL", "Correspondance partielle avec le registre des "
                             "gels des avoirs : vérification par le responsable conformité."))
        r.controle("gel_des_avoirs", gels.SOURCE, al, detail=res)

    # 6. TVA dans VIES (secondaire).
    if c_tva and c_tva["valide"] and c_tva.get("verifiable", True):
        try:
            v = await tva.verifier(client, c_tva["valeur"])
        except SourceIndisponible as e:
            r.panne("tva_vies", e, essentielle=False, code="TVA_NON_CONFIRMEE")
        else:
            al = [] if v["enregistre_vies"] else [alerte(A_VERIFIER, "TVA_NON_ENREGISTREE_VIES", "Le numéro de "
                                                          "TVA est bien formé mais n'est pas actif dans VIES.")]
            r.controle("tva_vies", tva.SOURCE, al, detail=v)
    else:
        r.controle("tva_vies", tva.SOURCE, non_demande=True)

    # 7. Adresse de la facture (secondaire).
    if adresse_facture:
        try:
            geo = await adresse.geocoder(client, texte(adresse_facture, 200))
        except SourceIndisponible as e:
            r.panne("adresse_facture", e, essentielle=False, code="ADRESSE_NON_VERIFIEE")
        else:
            al = []
            if geo is None or geo["score"] < config.SCORE_ADRESSE_MINIMUM:
                al.append(alerte(A_VERIFIER, "ADRESSE_INTROUVABLE", "L'adresse de la facture n'existe pas dans la "
                                 "Base Adresse Nationale (ou correspondance trop faible)."))
            elif fiche:
                communes = {e.get("commune_insee") for e in (fiche.get("etablissement_demande"), fiche.get("siege"))
                            if e and e.get("commune_insee")}
                if communes and geo["commune_insee"] not in communes:
                    al.append(alerte(A_VERIFIER, "ADRESSE_DIFFERENTE", f"L'adresse de la facture ({geo['commune']}) "
                                     "n'est pas dans la commune de l'établissement officiel."))
            r.controle("adresse_facture", adresse.SOURCE, al, detail=geo)
    else:
        r.controle("adresse_facture", adresse.SOURCE, non_demande=True)

    # 8. Montant en euros (essentiel si devise étrangère : les seuils en dépendent).
    if montant_dec is not None:
        try:
            conv = await change.convertir_en_euros(client, montant_dec, devise)
        except SourceIndisponible as e:
            r.panne("montant_eur", e, essentielle=True)
        else:
            m_eur = Decimal(conv["montant_eur"])
            r.donnees["montant_eur"] = conv["montant_eur"]
            al = []
            if m_eur >= config.SEUIL_DOUBLE_VALIDATION_EUR:
                al.append(alerte(A_VERIFIER, "DOUBLE_VALIDATION", f"{m_eur} € ≥ seuil de double validation "
                                 f"({config.SEUIL_DOUBLE_VALIDATION_EUR} €)."))
            r.controle("montant_eur", change.SOURCE if devise != "EUR" else "calcul local", al, detail=conv)
    else:
        r.controle("montant_eur", "calcul local", non_demande=True)

    return r.conclure()
