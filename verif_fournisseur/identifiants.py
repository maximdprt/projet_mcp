"""Contrôles de format des identifiants, calculés localement (aucun appel réseau).

Ces calculs sont déterministes : l'IA ne les fait jamais elle-même,
elle appelle l'outil, qui renvoie le résultat exact.

- SIREN (9 chiffres) et SIRET (14 chiffres) : algorithme de Luhn.
  Exception officielle : les établissements de La Poste (SIREN 356000000),
  dont le SIRET est valide si la somme de ses chiffres est divisible par 5.
- TVA intracommunautaire française : FR + clé (2 chiffres) + SIREN,
  avec clé = (12 + 3 × (SIREN mod 97)) mod 97.
- IBAN : norme ISO 13616 (longueur par pays + reste modulo 97 égal à 1).
"""

from __future__ import annotations

import re

SIREN_LA_POSTE = "356000000"

# Longueur officielle de l'IBAN pour les pays les plus fréquents (registre SWIFT).
LONGUEUR_IBAN = {
    "FR": 27, "MC": 27, "DE": 22, "BE": 16, "ES": 24, "IT": 27, "LU": 20,
    "NL": 18, "PT": 25, "CH": 21, "GB": 22, "IE": 22, "AT": 20, "PL": 28,
    "GR": 27, "FI": 18, "DK": 18, "SE": 24, "NO": 15, "CZ": 24, "RO": 24,
    "HU": 28, "BG": 22, "HR": 21, "SI": 19, "SK": 24, "EE": 20, "LV": 21,
    "LT": 20, "CY": 28, "MT": 31, "IS": 26, "LI": 21, "AD": 24, "SM": 27,
}
# Pays dont l'IBAN est au format français (France, DOM-TOM, Monaco).
PAYS_IBAN_FRANCAIS = {"FR", "MC", "GP", "MQ", "GF", "RE", "YT", "PM", "NC", "PF", "WF", "BL", "MF", "TF"}


def nettoyer(valeur: object) -> str:
    """Retire espaces, points et tirets ; passe en majuscules."""
    return re.sub(r"[\s.\-]", "", str(valeur or "")).upper()


def luhn_valide(chiffres: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(chiffres)):
        n = int(c)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _resultat(valeur: str, valide: bool, raison: str, **extra) -> dict:
    return {"valeur": valeur, "valide": valide, "raison": raison, **extra}


def controler_siren(valeur: object) -> dict:
    v = nettoyer(valeur)
    if not re.fullmatch(r"\d{9}", v):
        return _resultat(v, False, "Un SIREN contient exactement 9 chiffres.")
    if v == SIREN_LA_POSTE or luhn_valide(v):
        return _resultat(v, True, "Clé de contrôle (Luhn) correcte.")
    return _resultat(v, False, "Clé de contrôle (Luhn) incorrecte : numéro mal recopié ou inventé.")


def controler_siret(valeur: object) -> dict:
    v = nettoyer(valeur)
    if not re.fullmatch(r"\d{14}", v):
        return _resultat(v, False, "Un SIRET contient exactement 14 chiffres (SIREN + NIC).")
    siren = v[:9]
    if siren == SIREN_LA_POSTE:
        # Les établissements de La Poste suivent soit Luhn, soit la règle « somme des chiffres divisible par 5 ».
        ok = luhn_valide(v) or sum(int(c) for c in v) % 5 == 0
        return _resultat(v, ok, "Règle spécifique La Poste (Luhn ou somme des chiffres divisible par 5)"
                         + (" respectée." if ok else " non respectée."), siren=siren)
    if not luhn_valide(siren):
        return _resultat(v, False, "Le SIREN contenu dans ce SIRET a une clé de contrôle incorrecte.", siren=siren)
    if not luhn_valide(v):
        return _resultat(v, False, "Clé de contrôle (Luhn) du SIRET incorrecte : numéro mal recopié ou inventé.",
                         siren=siren)
    return _resultat(v, True, "Clé de contrôle (Luhn) correcte.", siren=siren)


def cle_tva_fr(siren: str) -> str:
    return f"{(12 + 3 * (int(siren) % 97)) % 97:02d}"


def controler_tva(valeur: object, siren_attendu: str | None = None) -> dict:
    v = nettoyer(valeur)
    m = re.fullmatch(r"FR([0-9A-Z]{2})(\d{9})", v)
    if not m:
        if re.fullmatch(r"[A-Z]{2}[0-9A-Z]{2,13}", v) and not v.startswith("FR"):
            return _resultat(v, False, "Numéro de TVA non français : ce serveur ne vérifie que les numéros FR.",
                             verifiable=False)
        return _resultat(v, False, "Format attendu : FR + 2 caractères de clé + SIREN (9 chiffres).")
    cle, siren = m.groups()
    if not controler_siren(siren)["valide"]:
        return _resultat(v, False, "Le SIREN contenu dans ce numéro de TVA est invalide.", siren=siren)
    if siren_attendu and siren != siren_attendu:
        return _resultat(v, False, f"Ce numéro de TVA correspond au SIREN {siren}, pas au SIREN {siren_attendu} "
                         "du fournisseur.", siren=siren)
    if not cle.isdigit():
        return _resultat(v, True, "Clé alphanumérique (ancien format) : non vérifiable par calcul, "
                         "SIREN cohérent.", siren=siren, verifiable=False)
    attendue = cle_tva_fr(siren)
    if cle != attendue:
        return _resultat(v, False, f"Clé de TVA incorrecte : pour ce SIREN la clé doit être {attendue}.",
                         siren=siren)
    return _resultat(v, True, "Clé de TVA cohérente avec le SIREN.", siren=siren)


def controler_iban(valeur: object) -> dict:
    v = nettoyer(valeur)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", v):
        return _resultat(v, False, "Format IBAN non reconnu (2 lettres pays + 2 chiffres de clé + compte).")
    pays = v[:2]
    attendue = LONGUEUR_IBAN.get(pays)
    if pays in PAYS_IBAN_FRANCAIS and attendue is None:
        attendue = 27
    if attendue and len(v) != attendue:
        return _resultat(v, False, f"Un IBAN {pays} doit contenir {attendue} caractères (ici {len(v)}).", pays=pays)
    rearrange = v[4:] + v[:4]
    nombre = "".join(str(int(c, 36)) for c in rearrange)
    if int(nombre) % 97 != 1:
        return _resultat(v, False, "Clé de contrôle IBAN (modulo 97) incorrecte : numéro mal recopié ou falsifié.",
                         pays=pays)
    return _resultat(v, True, "Clé de contrôle IBAN correcte. Attention : cela ne prouve pas à qui "
                     "appartient le compte.", pays=pays, est_francais=pays in PAYS_IBAN_FRANCAIS)
