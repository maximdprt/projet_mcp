"""Configuration lue côté serveur, dans le fichier .env (jamais transmise à l'IA).

Les six API externes sont ouvertes : aucune clé. La SEULE clé du projet est celle du CRM
(CRM_CLE_MCP). Elle reste dans le .env du serveur MCP : l'IA ne la voit jamais, et elle ne
donne que le droit d'enregistrer un résultat de vérification (pas de payer, pas de modifier un IBAN).
"""

import os
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

# "reel" : vraies API publiques. "simulation" : API simulées (démo hors ligne, déterministe).
MODE = os.getenv("VERIF_MODE", "reel").strip().lower()

USER_AGENT = os.getenv("VERIF_USER_AGENT", "verif-fournisseur-mcp/2.0 (projet etudiant)")
TIMEOUT_SECONDES = float(os.getenv("VERIF_TIMEOUT_SECONDES", "10"))
TIMEOUT_GELS_SECONDES = float(os.getenv("VERIF_TIMEOUT_GELS_SECONDES", "30"))
APPELS_PAR_SECONDE = float(os.getenv("VERIF_APPELS_PAR_SECONDE", "5"))  # limite documentée : 7/s
DELAI_NOUVEL_ESSAI = float(os.getenv("VERIF_DELAI_NOUVEL_ESSAI", "1"))
CACHE_GELS_HEURES = float(os.getenv("VERIF_CACHE_GELS_HEURES", "6"))

# Règles métier (déterministes, réglables, jamais décidées par l'IA)
JOURS_ENTREPRISE_RECENTE = int(os.getenv("VERIF_JOURS_ENTREPRISE_RECENTE", "180"))
SEUIL_DOUBLE_VALIDATION_EUR = Decimal(os.getenv("VERIF_SEUIL_DOUBLE_VALIDATION_EUR", "10000"))
FACTEUR_MONTANT_ANORMAL = Decimal(os.getenv("VERIF_FACTEUR_MONTANT_ANORMAL", "3"))
SCORE_ADRESSE_MINIMUM = float(os.getenv("VERIF_SCORE_ADRESSE_MINIMUM", "0.5"))

# CRM
CRM_URL = os.getenv("CRM_URL", "http://127.0.0.1:8000")
CRM_CLE_MCP = os.getenv("CRM_CLE_MCP", "cle-mcp-demo-a-changer")
