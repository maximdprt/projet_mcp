"""Génère les factures PDF du jeu de test (fictives, marquées comme telles), sans dépendance externe.

Chaque PDF reprend une facture de `donnees_demo.SCENARIOS` avec des libellés standard (« SIRET : », « IBAN : »,
« Total TTC : »…) : le CRM les relit ensuite avec `extraction.py`, comme n'importe quelle facture déposée.
Police Helvetica standard, encodage WinAnsi (accents français et symbole euro).
"""

from __future__ import annotations

import textwrap
from datetime import date

LARGEUR, HAUTEUR = 595, 842   # A4 en points


def _texte_pdf(s: str) -> str:
    s = str(s).replace(" ", " ").replace(" ", " ")
    sortie = []
    for b in s.encode("cp1252", errors="replace"):
        c = chr(b)
        if c in "()\\":
            sortie.append("\\" + c)          # caractères spéciaux des chaînes PDF
        elif 32 <= b < 127:
            sortie.append(c)
        else:
            sortie.append(f"\\{b:03o}")      # accents, €, apostrophes typographiques (octal WinAnsi)
    return "".join(sortie)


def _montant_affiche(montant: str, devise: str) -> str:
    entier, _, dec = f"{montant}".partition(".")
    groupes = f"{int(entier):,}".replace(",", " ")
    return f"{groupes},{(dec or '00').ljust(2, '0')[:2]} {'€' if devise == 'EUR' else devise}"


def _date_fr(iso: str | None) -> str:
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return ""


class _Page:
    def __init__(self) -> None:
        self.ops: list[str] = []

    def rect(self, x, y, l, h, r, g, b) -> None:
        self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x} {y} {l} {h} re f")

    def ligne(self, x1, y1, x2, y2, gris=0.85) -> None:
        self.ops.append(f"{gris:.2f} G 0.8 w {x1} {y1} m {x2} {y2} l S")

    def texte(self, x, y, s, taille=10, gras=False, couleur=(0.1, 0.12, 0.2)) -> None:
        r, g, b = couleur
        self.ops.append(f"BT /{'F2' if gras else 'F1'} {taille} Tf {r:.3f} {g:.3f} {b:.3f} rg {x} {y} Td "
                        f"({_texte_pdf(s)}) Tj ET")

    def flux(self) -> bytes:
        return "\n".join(self.ops).encode("latin-1")


def _assembler(contenu: bytes) -> bytes:
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {LARGEUR} {HAUTEUR}] "
        f"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        f"<< /Length {len(contenu)} >>\nstream\n".encode() + contenu + b"\nendstream",
    ]
    sortie = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    positions = []
    for i, obj in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    debut_xref = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode()
    sortie += b"".join(f"{p:010d} 00000 n \n".encode() for p in positions)
    sortie += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{debut_xref}\n%%EOF\n".encode()
    return bytes(sortie)


def facture_pdf(f: dict) -> bytes:
    """PDF d'une facture du jeu de test."""
    p = _Page()
    indigo, blanc, doux = (0.31, 0.27, 0.90), (1, 1, 1), (0.36, 0.40, 0.50)
    # bandeau
    p.rect(0, HAUTEUR - 96, LARGEUR, 96, *indigo)
    p.texte(40, HAUTEUR - 50, f.get("nom_emetteur") or "Émetteur inconnu", 20, True, blanc)
    p.texte(40, HAUTEUR - 72, "EXEMPLE - FACTURE FICTIVE DU JEU DE TEST", 9, True, (0.85, 0.85, 1))
    p.texte(LARGEUR - 150, HAUTEUR - 52, "FACTURE", 22, True, blanc)
    # références
    y = HAUTEUR - 135
    p.texte(40, y, f"Facture n° : {f.get('numero', '')}", 11, True)
    p.texte(330, y, f"Date d'émission : {_date_fr(f.get('date_emission'))}", 11)
    # émetteur
    y -= 40
    p.texte(40, y, "ÉMETTEUR", 8, True, doux)
    lignes = [f"Fournisseur : {f.get('nom_emetteur') or ''}", f"Adresse : {f.get('adresse_emetteur') or ''}",
              f"SIRET : {f.get('siret') or ''}", f"TVA : {f.get('tva') or ''}"]
    for i, s in enumerate(lignes):
        p.texte(40, y - 18 - i * 16, s, 10)
    p.texte(330, y, "CLIENT", 8, True, doux)
    p.texte(330, y - 18, "Démo SaaS Vérif Fournisseur", 10)
    p.texte(330, y - 34, "Service comptabilité fournisseurs", 10)
    # tableau
    y -= 110
    p.rect(40, y - 6, LARGEUR - 80, 24, 0.94, 0.95, 0.97)
    p.texte(50, y + 2, "Désignation", 9, True, doux)
    p.texte(LARGEUR - 160, y + 2, "Montant", 9, True, doux)
    objet = textwrap.wrap(str(f.get("objet") or "Prestation"), 70) or ["Prestation"]
    y -= 26
    for i, s in enumerate(objet):
        p.texte(50, y - i * 14, ("Objet : " if i == 0 else "") + s, 10)
    montant = _montant_affiche(f.get("montant", "0.00"), f.get("devise", "EUR"))
    p.texte(LARGEUR - 160, y, montant, 10)
    y -= 14 * len(objet) + 16
    p.ligne(40, y, LARGEUR - 40, y)
    p.texte(LARGEUR - 260, y - 24, f"Total TTC : {montant}", 13, True)
    p.texte(40, y - 24, f"Devise : {f.get('devise', 'EUR')}", 10, False, doux)
    # règlement
    y -= 80
    p.texte(40, y, "RÈGLEMENT PAR VIREMENT", 8, True, doux)
    p.texte(40, y - 18, f"IBAN : {f.get('iban') or ''}", 11, True)
    p.texte(40, y - 36, "Échéance : 30 jours à réception", 10)
    # pied
    p.ligne(40, 70, LARGEUR - 40, 70)
    p.texte(40, 52, "Document fictif généré pour le jeu de test de Vérif Fournisseur (données de démonstration).", 8,
            False, doux)
    p.texte(40, 40, "Ne pas utiliser comme facture réelle.", 8, False, doux)
    return _assembler(p.flux())
