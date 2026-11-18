"""Les 3 outils du MCP, un fichier chacun. Le serveur (verif_fournisseur/mcp/serveur.py) les expose à l'IA."""

from .rechercher_entreprise import rechercher_entreprise
from .traiter_factures_crm import traiter_factures_crm
from .verifier_fournisseur import verifier_fournisseur

__all__ = ["rechercher_entreprise", "verifier_fournisseur", "traiter_factures_crm"]
