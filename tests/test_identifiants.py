"""Calculs locaux : SIREN, SIRET, TVA, IBAN."""

from verif_fournisseur.identifiants import (cle_tva_fr, controler_iban, controler_siren, controler_siret,
                                            controler_tva)


def test_siren_et_siret_valides():
    assert controler_siren("130 025 265")["valide"]
    assert controler_siret("130 025 265 00013")["valide"]


def test_siren_une_faute_de_frappe_est_detectee():
    assert not controler_siren("130025266")["valide"]
    assert not controler_siret("13002526500014")["valide"]


def test_mauvais_nombre_de_chiffres():
    assert not controler_siren("12345")["valide"]
    assert not controler_siret("1300252650001")["valide"]


def test_exception_officielle_la_poste():
    assert controler_siret("35600000000048")["valide"]       # siège (Luhn)
    assert controler_siret("35600000049837")["valide"]       # somme des chiffres = 45, divisible par 5


def test_cle_tva_calculee():
    assert cle_tva_fr("130025265") == "07"
    assert controler_tva("FR07130025265")["valide"]
    assert not controler_tva("FR08130025265")["valide"]


def test_tva_qui_ne_correspond_pas_au_siren_du_fournisseur():
    r = controler_tva("FR40303265045", siren_attendu="130025265")
    assert not r["valide"] and "pas au SIREN" in r["raison"]


def test_iban():
    assert controler_iban("FR76 3000 6000 0112 3456 7890 189")["valide"]
    assert not controler_iban("FR76 3000 6000 0112 3456 7890 188")["valide"]   # un chiffre changé
    assert not controler_iban("FR76 3000 6000 0112 3456 7890")["valide"]       # trop court
    de = controler_iban("DE89 3704 0044 0532 0130 00")
    assert de["valide"] and not de["est_francais"]


def test_iban_valide_rappelle_que_le_titulaire_n_est_pas_verifie():
    assert "ne prouve pas à qui appartient" in controler_iban("FR7630006000011234567890189")["raison"]

