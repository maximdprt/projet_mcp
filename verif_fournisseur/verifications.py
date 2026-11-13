"""Le cœur métier : valider les entrées, interroger les sources, appliquer les règles, conclure.

Les fonctions reçoivent les clients HTTP en paramètre : vrais clients en production, faux dans les tests.
Chaque rapport liste TOUS les contrôles, toujours dans le même ordre, avec leur source et leur résultat :
OK, ALERTE, INDISPONIBLE ou NON_DEMANDE. Rien n'est laissé à l'interprétation de l'IA.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal

import httpx

from . import config, crm_client
from .identifiants import controler_iban, controler_siret, controler_tva, nettoyer
from .regles import (A_VERIFIER, BLOQUANT, INFO, MESSAGES, RAPPELS, STATUT_CRM, alerte, alertes_procedures,
                     analyser_procedures, anciennete_jours, comparer_noms, parser_montant, regles_crm,
                     statut_final)
from .sources import adresse, bodacc, change, entreprises, gels, tva
from .sources.http import SourceIndisponible, maintenant, texte


def _refus(motif: str, **extra) -> dict:
    return {"refus": True, "motif": motif, **extra}


class _Rapport:
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


# --------------------------------------------------------------------------- #
# Outil 1 : rechercher une entreprise par son nom
# --------------------------------------------------------------------------- #

async def rechercher_entreprise(client: httpx.AsyncClient, nom: str, code_postal: str | None = None) -> dict:
    nom = (nom or "").strip()
    if re.fullmatch(r"[\d\s]{9,17}", nom):
        return _refus("C'est un numéro, pas un nom : utiliser verifier_fournisseur avec ce SIRET.")
    if not 3 <= len(nom) <= 100:
        return _refus("Le nom recherché doit contenir entre 3 et 100 caractères.")
    if code_postal and not re.fullmatch(r"\d{5}", code_postal.strip()):
        return _refus("Le code postal doit contenir 5 chiffres.")
    try:
        data = await entreprises.chercher_par_nom(client, nom, code_postal.strip() if code_postal else None)
    except SourceIndisponible as e:
        return {"erreur": "SOURCE_INDISPONIBLE", "source": e.source, "raison": e.raison,
                "consigne": "Aucune conclusion possible : réessayer plus tard."}
    candidats = []
    for r in (data or {}).get("results") or []:
        f = entreprises.extraire(r)
        candidats.append({k: f[k] for k in ("siren", "nom_officiel", "sigle", "etat_administratif",
                                            "date_creation", "siege")})
    total = (data or {}).get("total_results", len(candidats))
    if not candidats:
        consigne = ("Aucune entreprise trouvée dans la base publique. Cela ne prouve PAS qu'elle n'existe pas. "
                    "Demander le SIRET imprimé sur la facture.")
    elif total > 1:
        consigne = ("Plusieurs entreprises correspondent : ne pas choisir à la place de l'utilisateur. Demander le "
                    "SIRET imprimé sur la facture, puis appeler verifier_fournisseur.")
    else:
        consigne = "Un seul résultat, mais un nom ne suffit pas : confirmer avec le SIRET imprimé sur la facture."
    return {"mode": config.MODE, "recherche": nom, "nombre_total_resultats": total, "candidats": candidats,
            "consigne": consigne, "source": entreprises.SOURCE, "consulte_le": maintenant()}


# --------------------------------------------------------------------------- #
# Outil 2 : vérifier un fournisseur (6 API + calculs locaux)
# --------------------------------------------------------------------------- #

async def verifier_fournisseur(client: httpx.AsyncClient, siret: str, nom_sur_facture: str,
                               iban: str | None = None, tva_facture: str | None = None,
                               adresse_facture: str | None = None, montant: object = None,
                               devise: str = "EUR", aujourd_hui: date | None = None) -> dict:
    nom_sur_facture = texte(nom_sur_facture, 200) or ""
    if len(nom_sur_facture) < 2:
        return _refus("Indiquer le nom du fournisseur tel qu'il est écrit sur la facture.")
    if not siret:
        return _refus("Le SIRET imprimé sur la facture est obligatoire : un nom seul ne suffit pas (homonymes). "
                      "Ne jamais deviner ni inventer un SIRET.")
    devise = (devise or "EUR").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", devise):
        return _refus("La devise doit être un code ISO à 3 lettres (EUR, USD, GBP…).")
    montant_dec = None
    if montant not in (None, ""):
        try:
            montant_dec = parser_montant(montant)
        except ValueError as e:
            return _refus(str(e))

    r = _Rapport(nom_sur_facture=nom_sur_facture)

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


# --------------------------------------------------------------------------- #
# Outil 3 : traiter les factures du CRM (lit, vérifie, enregistre le résultat — ne paie jamais)
# --------------------------------------------------------------------------- #

def empreinte(rapport: dict) -> str:
    return hashlib.sha256(json.dumps(rapport, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def resume_controles(controles: list[dict]) -> list[dict]:
    """Ce que le CRM garde de chaque contrôle : nom, source, résultat, raison d'une panne. Jamais le détail
    (données d'entreprise, annonces…) : le CRM n'en a pas besoin pour afficher la décision."""
    limites = {"controle": 40, "source": 120, "raison": 200}
    return [{"resultat": c["resultat"], **{k: texte(c[k], n) for k, n in limites.items() if c.get(k)}}
            for c in controles[:20]]


async def _traiter_une(ext: httpx.AsyncClient, crm: httpx.AsyncClient, facture_id: str,
                       aujourd_hui: date | None) -> dict:
    f = await crm_client.facture(crm, facture_id)
    if f is None:
        return _refus(f"Facture {facture_id} introuvable dans le CRM.")
    if f.get("statut") == "payee":
        return _refus(f"Facture {facture_id} déjà payée : aucune modification.", facture_id=facture_id)
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
                return _refus("Identifiant de facture invalide (lettres, chiffres et tirets, 3 à 30 caractères).")
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
