"""Lecture d'une facture déposée (PDF texte, TXT ou JSON) : extraction déterministe des champs.

Aucune IA ici : des libellés usuels (« SIRET », « IBAN », « Total TTC »…) et des expressions régulières.
Ce qui n'est pas trouvé est signalé comme manquant ; l'utilisateur complète avant l'analyse par le MCP.
Le texte lu est une DONNÉE : il est nettoyé, borné, et n'est jamais interprété comme une instruction.
PDF scannés (images) : non pris en charge (pas d'OCR) ; le champ « manquants » le fait apparaître.
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TAILLE_MAX = 5 * 1024 * 1024          # 5 Mo
PAGES_MAX = 10
CHAMPS = ("numero", "date_emission", "nom_emetteur", "siret", "tva", "iban", "adresse_emetteur", "montant",
          "devise", "objet")
OBLIGATOIRES = ("numero", "nom_emetteur", "siret", "montant")
LIMITES = {"numero": 40, "nom_emetteur": 120, "siret": 20, "tva": 20, "iban": 40, "adresse_emetteur": 200,
           "objet": 500, "devise": 3, "date_emission": 10, "montant": 16}
DEVISES = {"€": "EUR", "EUR": "EUR", "EUROS": "EUR", "$": "USD", "USD": "USD", "£": "GBP", "GBP": "GBP", "CHF": "CHF"}
LIBELLES = r"(?:facture|date|fournisseur|[ée]metteur|vendeur|adresse|siret|siren|tva|iban|bic|objet|d[ée]signation|" \
           r"total|montant|net|devise|[ée]ch[ée]ance|client|r[èe]glement)"


class FichierRefuse(ValueError):
    """Fichier vide, trop gros, d'un type non pris en charge ou illisible."""


def _nettoyer(valeur: object, champ: str) -> str | None:
    if valeur is None:
        return None
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(valeur))
    s = re.sub(r"\s+", " ", s).strip()
    return s[: LIMITES.get(champ, 200)] or None


def normaliser_montant(texte: str | None) -> str | None:
    """« 4 180,00 » / « 4,180.00 » / « 4180 » -> « 4180.00 » (Decimal, arrondi au centime)."""
    if not texte:
        return None
    s = re.sub(r"[\s  ']", "", str(texte))
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if d < 0 or d > Decimal("999999999"):
        return None
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def lire_texte(nom_fichier: str, contenu: bytes) -> str:
    """Texte brut d'un PDF (couche texte) ou d'un fichier texte."""
    if not contenu:
        raise FichierRefuse("Fichier vide.")
    if len(contenu) > TAILLE_MAX:
        raise FichierRefuse("Fichier trop volumineux (5 Mo maximum).")
    if contenu[:5] == b"%PDF-":
        try:
            from pypdf import PdfReader
            lecteur = PdfReader(io.BytesIO(contenu))
            return "\n".join((page.extract_text() or "") for page in lecteur.pages[:PAGES_MAX])
        except Exception as e:  # PDF corrompu ou chiffré
            raise FichierRefuse(f"PDF illisible ({type(e).__name__}).") from None
    if nom_fichier.lower().endswith((".txt", ".text", ".csv", ".json")):
        return contenu.decode("utf-8", errors="replace")
    raise FichierRefuse("Type de fichier non pris en charge : déposer un PDF, un TXT ou un JSON.")


def _cherche(motif: str, texte: str) -> str | None:
    m = re.search(motif, texte, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else None


def extraire_texte(texte: str) -> dict:
    """Champs d'une facture à partir de son texte."""
    t = texte.replace(" ", " ").replace(" ", " ")
    champs: dict[str, str | None] = {k: None for k in CHAMPS}
    champs["numero"] = _cherche(r"facture\s*(?:n\s*[°o]|num[ée]ro|no\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/_.]{0,39})", t)
    d = re.search(r"(?:date(?:\s+d['’]\s*[ée]mission)?|[ée]mise?\s+le)\s*[:\-]?\s*(\d{2})[/.\-](\d{2})[/.\-](\d{4})", t, re.I)
    if d:
        try:
            champs["date_emission"] = date(int(d.group(3)), int(d.group(2)), int(d.group(1))).isoformat()
        except ValueError:
            pass
    champs["nom_emetteur"] = _cherche(r"^\s*(?:fournisseur|[ée]metteur|vendeur|raison sociale)\s*[:\-]\s*(.+)$", t)
    siret = _cherche(r"siret\s*[:\-]?\s*((?:\d[ .]?){14})", t)
    champs["siret"] = re.sub(r"\D", "", siret) if siret else None
    tva = _cherche(r"(?:tva(?:\s+intracom\w*)?|vat)\s*[:\-]?\s*([A-Z]{2}[ ]?[0-9A-Z]{2}(?:[ ]?\d{3}){3})", t)
    champs["tva"] = tva.replace(" ", "").upper() if tva else None
    iban = _cherche(r"iban\s*[:\-]?\s*([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){10,30})", t)
    champs["iban"] = iban.replace(" ", "").upper() if iban else None
    champs["adresse_emetteur"] = _cherche(r"^\s*adresse\s*[:\-]\s*(.+)$", t)
    # montant : le libellé le plus explicite l'emporte
    for libelle in (r"total\s*ttc", r"net\s*[àa]\s*payer", r"montant\s*(?:ttc|total|d[ûu])", r"total"):
        m = re.search(libelle + r"\s*[:\-]?\s*([\d][\d ., ']*\d)\s*(€|eur(?:os)?|usd|\$|gbp|£|chf)?", t, re.I)
        if m:
            champs["montant"] = normaliser_montant(m.group(1))
            if m.group(2):
                champs["devise"] = DEVISES.get(m.group(2).upper())
            break
    devise = _cherche(r"devise\s*[:\-]\s*([A-Z]{3})\b", t)
    if devise:
        champs["devise"] = devise.upper()
    # objet : la ligne « Objet : » et ses lignes de continuation (jusqu'au libellé suivant)
    lignes = t.splitlines()
    for i, ligne in enumerate(lignes):
        m = re.match(r"^\s*(?:objet|d[ée]signation)\s*[:\-]\s*(.+)$", ligne, re.I)
        if m:
            morceaux = [m.group(1)]
            for suite in lignes[i + 1:]:
                if not suite.strip() or re.match(r"^\s*" + LIBELLES + r"\b", suite, re.I) or re.search(r"\d,\d{2} ", suite):
                    break
                morceaux.append(suite.strip())
            objet = " ".join(morceaux)
            champs["objet"] = re.sub(r"\s+\d[\d ]*,\d{2}\s*(?:€|[A-Z]{3})\s*$", "", objet)   # montant en fin de ligne
            break
    return _finaliser(champs)


def extraire_json(contenu: bytes) -> dict:
    """Facture fournie en JSON (export d'un autre logiciel) : seules les clés connues sont gardées."""
    try:
        data = json.loads(contenu.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise FichierRefuse("JSON illisible.") from None
    if not isinstance(data, dict):
        raise FichierRefuse("Le JSON doit être un objet (une facture).")
    alias = {"adresse": "adresse_emetteur", "fournisseur": "nom_emetteur", "emetteur": "nom_emetteur",
             "date": "date_emission", "montant_ttc": "montant"}
    champs = {k: None for k in CHAMPS}
    for cle, valeur in data.items():
        cle = alias.get(cle, cle)
        if cle in champs and isinstance(valeur, (str, int, float)) and not isinstance(valeur, bool):
            champs[cle] = str(valeur)
    champs["montant"] = normaliser_montant(champs["montant"])
    for cle in ("siret", "tva", "iban"):
        if champs[cle]:
            champs[cle] = re.sub(r"\s", "", champs[cle]).upper()
    if champs["siret"]:
        champs["siret"] = re.sub(r"\D", "", champs["siret"])
    return _finaliser(champs)


def _finaliser(champs: dict) -> dict:
    propres = {k: _nettoyer(champs.get(k), k) for k in CHAMPS}
    if propres["devise"] and not re.fullmatch(r"[A-Z]{3}", propres["devise"]):
        propres["devise"] = None
    if propres["date_emission"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", propres["date_emission"]):
        propres["date_emission"] = None
    propres["devise"] = propres["devise"] or "EUR"
    return {"champs": propres, "manquants": [k for k in OBLIGATOIRES if not propres[k]]}


def extraire(nom_fichier: str, contenu: bytes) -> dict:
    """Point d'entrée : un fichier déposé -> champs extraits + champs obligatoires manquants."""
    nom = _nettoyer(nom_fichier, "objet") or "facture"
    if nom.lower().endswith(".json"):
        if len(contenu) > TAILLE_MAX:
            raise FichierRefuse("Fichier trop volumineux (5 Mo maximum).")
        return extraire_json(contenu)
    texte = lire_texte(nom, contenu)
    if not texte.strip():
        raise FichierRefuse("Aucun texte lisible : PDF scanné (image) ? L'OCR n'est pas pris en charge.")
    return extraire_texte(texte)


def normaliser_nom(nom: str | None) -> str:
    s = unicodedata.normalize("NFKD", str(nom or "")).encode("ascii", "ignore").decode().upper()
    return " ".join(re.findall(r"[A-Z0-9]+", s))
