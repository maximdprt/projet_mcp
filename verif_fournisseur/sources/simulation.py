"""Mode simulation : les 6 API externes simulées, pour une démo hors ligne et 100 % reproductible.

Activé par VERIF_MODE=simulation. Chaque rapport porte alors "mode": "simulation".
Les entreprises ci-dessous sont FICTIVES (sauf la DINUM, reprise de la base publique) ; leurs numéros
respectent les vraies clés de contrôle. Les réponses imitent le format exact des vraies API.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from urllib.parse import parse_qs

import httpx

from ..identifiants import cle_tva_fr


def iban_fr(bban: str) -> str:
    """Construit un IBAN français valide (clé ISO 13616) à partir d'un BBAN de 23 caractères."""
    num = "".join(str(int(c, 36)) for c in bban + "FR00")
    return f"FR{98 - int(num) % 97:02d}{bban}"


def _il_y_a(jours: int) -> str:
    return (date.today() - timedelta(days=jours)).isoformat()


def _entreprise(siren, siret, nom, adresse, cp, commune, creation, etat="A", fermeture=None, sigle=None):
    etab = {"siret": siret, "est_siege": True, "etat_administratif": etat, "adresse": adresse, "code_postal": cp,
            "commune": commune, "date_fermeture": fermeture, "liste_enseignes": [], "nom_commercial": None}
    return {"siren": siren, "nom_complet": nom, "nom_raison_sociale": nom, "sigle": sigle, "etat_administratif": etat,
            "date_creation": creation, "date_fermeture": fermeture, "nature_juridique": "5710",
            "activite_principale": "62.02A", "statut_diffusion": "O", "nombre_etablissements_ouverts": 1,
            "siege": etab, "matching_etablissements": [etab], "date_mise_a_jour": "2026-11-10T03:00:00",
            "complements": {"est_entrepreneur_individuel": False},
            "dirigeants": [{"nom": "EXEMPLE", "prenoms": "Personne", "type_dirigeant": "personne physique"}]}


ENTREPRISES = {e["siren"]: e for e in [
    _entreprise("130025265", "13002526500013", "DIRECTION INTERMINISTERIELLE DU NUMERIQUE",
                "20 AVENUE DE SEGUR 75007 PARIS", "75007", "75107", "2019-10-25", sigle="DINUM"),
    _entreprise("901234567", "90123456700013", "ATELIER MERCIER", "45 COURS GAMBETTA 69003 LYON", "69003", "69383",
                "2012-03-14"),
    _entreprise("902345677", "90234567700014", "IMPRIMERIE DU NORD", "8 RUE NATIONALE 59000 LILLE", "59000",
                "59350", "2008-09-01"),
    _entreprise("903456788", "90345678800012", "TRANSPORTS LEGRAND", "3 AVENUE DU PORT 13002 MARSEILLE", "13002",
                "13202", "2001-05-20", etat="C", fermeture="2025-06-30"),
    _entreprise("904567898", "90456789800013", "NEOTECH SOLUTIONS", "10 RUE DU FAUBOURG 75011 PARIS", "75011",
                "75111", _il_y_a(40)),
    _entreprise("905678918", "90567891800012", "GLOBAL TRADING HOLDING", "1 PLACE DE LA BOURSE 75002 PARIS",
                "75002", "75102", "2015-01-12"),
    _entreprise("906789128", "90678912800012", "CABINET ROUSSEAU CONSEIL", "22 RUE SAINTE CATHERINE 33000 BORDEAUX",
                "33000", "33063", "2010-11-03"),
    # Exemple « agent IA qui achète un casque » : un revendeur établi, une boutique créée il y a 12 jours
    _entreprise("907891238", "90789123800004", "SON ET IMAGE DISTRIBUTION",
                "15 RUE DE SEVRES 92100 BOULOGNE-BILLANCOURT", "92100", "92012", "2009-04-06"),
    _entreprise("908912348", "90891234800004", "HIGH TECH OUTLET", "27 RUE OBERKAMPF 75011 PARIS", "75011", "75111",
                _il_y_a(12)),
]}


def _annonce(siren, n, famille, nature, jours):
    return {"id": f"A2026SIM{n}", "dateparution": _il_y_a(jours), "familleavis": famille, "typeavis": "annonce",
            "tribunal": "TRIBUNAL DE COMMERCE (SIMULATION)",
            "listepersonnes": json.dumps({"personne": {"typePersonne": "pm",
                                                       "numeroImmatriculation": {"numeroIdentification": siren}}}),
            "jugement": json.dumps({"nature": nature, "date": _il_y_a(jours),
                                    "complementJugement": "Mandataire judiciaire : Maître EXEMPLE"})}


BODACC = {
    "902345677": [_annonce("902345677", 1, "collective", "Jugement d'ouverture de liquidation judiciaire", 60)],
    "906789128": [_annonce("906789128", 2, "collective",
                           "Jugement d'ouverture d'une procédure de redressement judiciaire", 120)],
    "903456788": [_annonce("903456788", 3, "radiation", None, 500)],
}

GELS = {"Publications": {"DatePublication": "2026-11-12T08:00:00", "PublicationDetail": [
    {"IdRegistre": 9001, "Nature": "Personne morale", "Nom": "GLOBAL TRADING HOLDING",
     "RegistreDetail": [{"TypeChamp": "ALIAS", "Valeur": [{"Alias": "GTH LIMITED"}]}]},
    {"IdRegistre": 9002, "Nature": "Personne morale", "Nom": "NORTHERN SHIPPING COMPANY", "RegistreDetail": []},
    {"IdRegistre": 9003, "Nature": "Personne physique", "Nom": "EXEMPLE",
     "RegistreDetail": [{"TypeChamp": "PRENOM", "Valeur": [{"Prenom": "Jean"}]}]},
]}}

# Adresses connues de la Base Adresse Nationale simulée : code postal -> code INSEE
COMMUNES = {"75007": ("75107", "Paris 7e"), "69003": ("69383", "Lyon 3e"), "59000": ("59350", "Lille"),
            "13002": ("13202", "Marseille 2e"), "75011": ("75111", "Paris 11e"), "75002": ("75102", "Paris 2e"),
            "33000": ("33063", "Bordeaux"), "92100": ("92012", "Boulogne-Billancourt")}

TAUX_BCE = {"USD": "0.9200", "GBP": "1.1700", "CHF": "1.0600"}


def _json(status: int, data) -> httpx.Response:
    return httpx.Response(status, json=data)


def _recherche(params: dict) -> httpx.Response:
    q = params.get("q", "")
    chiffres = re.sub(r"\D", "", q)
    if len(chiffres) in (9, 14) and chiffres == q.replace(" ", ""):
        res = [e for e in ENTREPRISES.values() if e["siren"] == chiffres[:9]]
    else:
        mots = q.upper().split()
        res = [e for e in ENTREPRISES.values() if all(m in e["nom_complet"] for m in mots)]
    return _json(200, {"results": res[:5], "total_results": len(res), "page": 1, "per_page": 5})


def _bodacc(params: dict) -> httpx.Response:
    m = re.search(r'registre="(\d{9})"', params.get("where", ""))
    res = BODACC.get(m.group(1), []) if m else []
    return _json(200, {"total_count": len(res), "results": res})


def _geocodage(params: dict) -> httpx.Response:
    q = params.get("q", "").upper()
    m = re.search(r"\b(\d{5})\b", q)
    if "IMAGINAIRE" in q or not m:
        return _json(200, {"type": "FeatureCollection", "features": []})
    cp = m.group(1)
    insee, ville = COMMUNES.get(cp, (None, None))
    score = 0.93 if insee else 0.31
    return _json(200, {"type": "FeatureCollection", "features": [{"properties": {
        "label": q.title(), "score": score, "postcode": cp, "citycode": insee, "city": ville}}]})


def _vatcomply(params: dict) -> httpx.Response:
    n = params.get("vat_number", "").upper()
    m = re.fullmatch(r"FR(\d{2})(\d{9})", n)
    if not m:
        return _json(400, {"error": "Invalid VAT number format."})
    cle, siren = m.groups()
    valide = siren in ENTREPRISES and cle == cle_tva_fr(siren) and ENTREPRISES[siren]["etat_administratif"] == "A"
    return _json(200, {"valid": valide, "vat_number": siren, "name": "---", "address": "---", "country_code": "FR"})


def _frankfurter(params: dict) -> httpx.Response:
    base = params.get("base", "")
    if base not in TAUX_BCE:
        return _json(404, {"message": "not found"})
    return _json(200, {"amount": 1.0, "base": base, "date": _il_y_a(1), "rates": {"EUR": float(TAUX_BCE[base])}})


def gestionnaire(request: httpx.Request) -> httpx.Response:
    params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
    hote = request.url.host
    if hote == "recherche-entreprises.api.gouv.fr":
        return _recherche(params)
    if hote == "bodacc-datadila.opendatasoft.com":
        return _bodacc(params)
    if hote == "data.geopf.fr":
        return _geocodage(params)
    if hote == "gels-avoirs.dgtresor.gouv.fr":
        return _json(200, GELS)
    if hote == "api.vatcomply.com":
        return _vatcomply(params)
    if hote == "api.frankfurter.dev":
        return _frankfurter(params)
    return httpx.Response(404)


def transport_simule() -> httpx.MockTransport:
    return httpx.MockTransport(gestionnaire)
