"""Les règles de décision. Elles sont dans le code du serveur, jamais dans le prompt de l'IA.

Le serveur ne dit jamais « fiable ». Il renvoie l'un de ces quatre statuts :
- BLOQUER_LE_PAIEMENT           : au moins un fait rend le paiement anormal ;
- IMPOSSIBLE_DE_VERIFIER        : une source indispensable n'a pas répondu : on ne conclut pas ;
- VERIFICATION_HUMAINE_REQUISE  : un signal demande un contrôle par une personne ;
- AUCUNE_ALERTE_DETECTEE        : rien d'anormal dans les sources consultées
                                  (ce qui ne garantit PAS que le fournisseur est honnête).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from . import config

BLOQUANT, A_VERIFIER, INFO = "BLOQUANT", "A_VERIFIER", "INFO"

STATUT_BLOQUER = "BLOQUER_LE_PAIEMENT"
STATUT_IMPOSSIBLE = "IMPOSSIBLE_DE_VERIFIER"
STATUT_HUMAIN = "VERIFICATION_HUMAINE_REQUISE"
STATUT_OK = "AUCUNE_ALERTE_DETECTEE"

# Statut MCP -> statut de la facture dans le CRM
STATUT_CRM = {STATUT_BLOQUER: "bloquee", STATUT_IMPOSSIBLE: "impossible_de_verifier",
              STATUT_HUMAIN: "a_verifier_humain", STATUT_OK: "verifiee"}

MESSAGES = {
    STATUT_BLOQUER: "Ne pas payer en l'état : au moins une anomalie bloquante a été trouvée. Voir les alertes.",
    STATUT_IMPOSSIBLE: "Vérification impossible pour le moment (source indisponible). Ne pas payer sur la base "
                       "de cette analyse : réessayer plus tard ou vérifier manuellement.",
    STATUT_HUMAIN: "Un contrôle humain est nécessaire avant paiement. Voir les alertes.",
    STATUT_OK: "Aucune alerte détectée dans les sources consultées. Cela ne garantit pas que la facture est "
               "légitime : le titulaire de l'IBAN, en particulier, n'est pas vérifiable par ce serveur.",
}

RAPPELS = [
    "Le titulaire de l'IBAN n'est pas vérifiable ici. En cas de nouveau RIB, contre-appeler le fournisseur au "
    "numéro déjà connu (référentiel), jamais à celui écrit sur la facture.",
    "Ces contrôles décrivent la situation légale publique de l'entreprise, pas sa solvabilité ni son honnêteté.",
]

FORMES_JURIDIQUES = {
    "SAS", "SASU", "SARL", "EURL", "SA", "SNC", "SCI", "SCOP", "SCA", "SCS", "SELARL", "SELAS", "SEL",
    "EI", "EIRL", "GIE", "SC", "SCM", "SCP", "ASSOCIATION", "ETS", "ETABLISSEMENTS", "STE", "SOCIETE",
    "ET", "DE", "DU", "DES", "LA", "LE", "LES", "L", "D",
}


def alerte(niveau: str, code: str, message: str) -> dict:
    return {"niveau": niveau, "code": code, "message": message}


# --------------------------------------------------------------------------- #
# Montants (Decimal uniquement : jamais de float pour de l'argent)
# --------------------------------------------------------------------------- #

def parser_montant(valeur: object) -> Decimal:
    s = str(valeur).replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        m = Decimal(s)
    except InvalidOperation:
        raise ValueError("Montant illisible : utiliser des chiffres, ex. 4200.50") from None
    if not m.is_finite() or m <= 0 or m > Decimal("1000000000"):
        raise ValueError("Le montant doit être positif et inférieur à 1 milliard.")
    return m.quantize(Decimal("0.01"))


# --------------------------------------------------------------------------- #
# Comparaison du nom de la facture avec le nom officiel
# --------------------------------------------------------------------------- #

def normaliser_nom(nom: str | None) -> str:
    s = unicodedata.normalize("NFKD", str(nom or "")).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"\(.*?\)", " ", s)
    return " ".join(m for m in re.split(r"[^A-Z0-9]+", s) if m and m not in FORMES_JURIDIQUES)


def comparer_noms(nom_facture: str, noms_officiels: list[str]) -> dict:
    """« identique » seulement si les mots sont les mêmes (ou l'un contient tous les mots de l'autre, au moins
    2 mots). Une faute d'orthographe (NUMERIK / NUMERIQUE) n'est PAS identique : c'est la technique des
    imitateurs, donc « proche » -> contrôle humain."""
    nf = normaliser_nom(nom_facture)
    meilleur, ref, identique = 0.0, None, False
    for nom in noms_officiels:
        no = normaliser_nom(nom)
        if not nf or not no:
            continue
        mots_f, mots_o = set(nf.split()), set(no.split())
        egal = nf == no or (min(len(mots_f), len(mots_o)) >= 2 and (mots_f <= mots_o or mots_o <= mots_f))
        score = 1.0 if egal else SequenceMatcher(None, nf, no).ratio()
        if score > meilleur:
            meilleur, ref = score, nom
        identique = identique or egal
    verdict = "identique" if identique else ("proche" if meilleur >= 0.6 else "different")
    return {"nom_facture": nom_facture, "nom_officiel_le_plus_proche": ref,
            "similarite": round(meilleur, 2), "correspondance": verdict}


# --------------------------------------------------------------------------- #
# Lecture des annonces BODACC
# --------------------------------------------------------------------------- #

def _type_procedure(nature: str) -> str:
    for mot, libelle in (("liquidation", "liquidation judiciaire"), ("redressement", "redressement judiciaire"),
                         ("sauvegarde", "sauvegarde")):
        if mot in nature:
            return libelle
    return "procédure collective"


def analyser_procedures(annonces: list[dict]) -> dict:
    """État probable des procédures, en lisant les annonces de la plus ancienne à la plus récente."""
    etat, type_proc, depuis, radiation, conciliation = "AUCUNE", None, None, None, None
    for a in sorted(annonces, key=lambda x: x.get("date_parution") or ""):
        famille, nature = a.get("famille"), (a.get("nature_jugement") or "").lower()
        if famille == "radiation":
            radiation = a.get("date_parution")
        elif famille == "conciliation":
            conciliation = a.get("date_parution")
        elif famille in ("collective", "retablissement_professionnel"):
            if "clôture" in nature or "mettant fin" in nature:
                etat = "CLOTUREE"
            elif any(m in nature for m in ("ouverture", "conversion", "résolution du plan", "extension", "reprise")):
                etat, type_proc, depuis = "EN_COURS", _type_procedure(nature), a.get("date_parution")
            elif "plan" in nature:
                type_proc = type_proc if etat != "AUCUNE" else _type_procedure(nature)
                etat, depuis = "PLAN_EN_COURS", a.get("date_parution")
            elif etat == "AUCUNE":
                etat, type_proc, depuis = "EN_COURS_PROBABLE", _type_procedure(nature), a.get("date_parution")
    return {"etat": etat, "type": type_proc, "depuis": depuis,
            "radiation_publiee_le": radiation, "conciliation_publiee_le": conciliation}


def alertes_procedures(analyse: dict) -> list[dict]:
    res = []
    if analyse["etat"] in ("EN_COURS", "EN_COURS_PROBABLE", "PLAN_EN_COURS"):
        liquidation = analyse["type"] == "liquidation judiciaire" and analyse["etat"] == "EN_COURS"
        res.append(alerte(
            BLOQUANT if liquidation else A_VERIFIER,
            "LIQUIDATION_JUDICIAIRE" if liquidation else "PROCEDURE_COLLECTIVE",
            f"BODACC : {analyse['type'] or 'procédure collective'} ({analyse['etat'].lower().replace('_', ' ')}) "
            f"depuis le {analyse['depuis']}."
            + (" Les paiements doivent passer par le liquidateur, pas par le compte habituel." if liquidation else "")))
    if analyse["radiation_publiee_le"]:
        res.append(alerte(A_VERIFIER, "RADIATION_PUBLIEE",
                          f"Radiation publiée au BODACC le {analyse['radiation_publiee_le']}."))
    if analyse["conciliation_publiee_le"]:
        res.append(alerte(INFO, "CONCILIATION", f"Conciliation publiée le {analyse['conciliation_publiee_le']}."))
    return res


# --------------------------------------------------------------------------- #
# Règles propres au CRM (référentiel fournisseurs + historique des factures)
# --------------------------------------------------------------------------- #

def _iban(v: str | None) -> str:
    return re.sub(r"\s", "", str(v or "")).upper()


def regles_crm(facture: dict, fournisseur: dict | None, historique: list[dict],
               montant_eur: Decimal | None) -> list[dict]:
    res = []
    if fournisseur is None:
        res.append(alerte(A_VERIFIER, "FOURNISSEUR_INCONNU",
                          "Cette facture n'est rattachée à aucun fournisseur du référentiel : premier paiement, "
                          "contrôle humain obligatoire."))
        return res
    if re.sub(r"\D", "", str(facture.get("siret") or "")) != fournisseur.get("siret"):
        res.append(alerte(BLOQUANT, "SIRET_DIFFERENT_DU_REFERENTIEL",
                          f"Le SIRET de la facture ({facture.get('siret')}) n'est pas celui du fournisseur "
                          f"enregistré ({fournisseur.get('siret')})."))
    if facture.get("iban") and _iban(facture["iban"]) != _iban(fournisseur.get("iban_reference")):
        res.append(alerte(BLOQUANT, "IBAN_DIFFERENT_DU_REFERENTIEL",
                          "L'IBAN de la facture n'est pas l'IBAN enregistré pour ce fournisseur (signal n°1 de la "
                          f"fraude au changement de RIB). Contre-appeler au {fournisseur.get('telephone_reference')} "
                          "(numéro du référentiel), jamais au numéro de la facture."))
    for h in historique:
        if h["id"] != facture["id"] and h.get("numero") == facture.get("numero"):
            res.append(alerte(BLOQUANT, "DOUBLON_FACTURE",
                              f"Le numéro {facture.get('numero')} existe déjà (facture {h['id']}, statut "
                              f"{h.get('statut')}) : risque de double paiement."))
            break
    passees = [parser_montant(h["montant_eur"]) for h in historique
               if h["id"] != facture["id"] and h.get("statut") in ("payee", "verifiee") and h.get("montant_eur")]
    if montant_eur is not None and len(passees) >= 3:
        moyenne = (sum(passees) / len(passees)).quantize(Decimal("0.01"))
        if montant_eur > moyenne * config.FACTEUR_MONTANT_ANORMAL:
            res.append(alerte(A_VERIFIER, "MONTANT_ANORMAL",
                              f"{montant_eur} € : plus de {config.FACTEUR_MONTANT_ANORMAL} fois la moyenne des "
                              f"{len(passees)} factures précédentes ({moyenne} €)."))
    return res


# --------------------------------------------------------------------------- #
# Synthèse
# --------------------------------------------------------------------------- #

def anciennete_jours(date_creation: str | None, aujourd_hui: date | None = None) -> int | None:
    try:
        return ((aujourd_hui or date.today()) - date.fromisoformat(str(date_creation)[:10])).days
    except ValueError:
        return None


def statut_final(alertes: list[dict], sources_en_panne: list[str]) -> str:
    niveaux = {a["niveau"] for a in alertes}
    if BLOQUANT in niveaux:
        return STATUT_BLOQUER
    if sources_en_panne:
        return STATUT_IMPOSSIBLE
    if A_VERIFIER in niveaux:
        return STATUT_HUMAIN
    return STATUT_OK
