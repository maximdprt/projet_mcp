# Vérif Fournisseur — le MCP qui empêche l'IA de payer une fausse facture

Avant de payer une facture, l'IA appelle ce serveur MCP. Il vérifie le fournisseur dans **6 API publiques
officielles** et dans le **CRM** de l'entreprise, applique des règles écrites dans le code et rend un verdict :

| Verdict | Signification |
|---|---|
| `BLOQUER_LE_PAIEMENT` | au moins un fait rend le paiement anormal |
| `VERIFICATION_HUMAINE_REQUISE` | un signal demande un contrôle humain |
| `AUCUNE_ALERTE_DETECTEE` | rien d'anormal dans les sources (ce qui ne veut pas dire « fiable ») |
| `IMPOSSIBLE_DE_VERIFIER` | une source indispensable n'a pas répondu |

L'IA ne peut jamais payer : aucun outil ne le permet, et le CRM refuse la clé du MCP (403).

## Les deux choses à lancer

| Double-clic sur | Ce qui se passe |
|---|---|
| **`OUVRIR_LES_SLIDES.cmd`** | Les 6 slides de l'oral s'ouvrent dans le navigateur (aucune installation). `→` `←` slides, `F` plein écran, `N` notes. |
| **`LANCER_MCP_INSPECTOR.cmd`** | Démarre le CRM de démo, puis ouvre le **MCP Inspector** : **Connect** → **Tools** → **List Tools** → choisir un outil → **Run Tool**. |

Il suffit d'avoir **Python 3.10+** et **Node.js** installés : au premier double-clic, `LANCER_MCP_INSPECTOR.cmd`
crée l'environnement Python, installe les dépendances et crée le `.env` tout seul (1 à 2 minutes).

## Les 3 outils du MCP

| Outil | Quand | Exemple à essayer dans l'Inspector |
|---|---|---|
| `rechercher_entreprise` | on n'a qu'un nom | `nom` = `ATELIER MERCIER` |
| `verifier_fournisseur` | une facture devant soi (8 contrôles) | `siret` = `90567891800012`, `nom_sur_facture` = `GLOBAL TRADING HOLDING` → **bloqué** (gel des avoirs) |
| `traiter_factures_crm` | factures du CRM (lit, vérifie, écrit le verdict) | `facture_id` = `F02` → **bloqué** (fraude au RIB) ; vide = les 16 factures |

Autres essais avec `verifier_fournisseur` :
- `siret` = `13002526500014`, `nom_sur_facture` = `DINUM` : SIRET à clé fausse, refusé sans appel réseau.
- `siret` = `90891234800004`, `nom_sur_facture` = `HIGH TECH OUTLET` : boutique créée il y a 12 jours, contrôle humain.

Le CRM repart à chaque démarrage avec **16 factures piégées** (F01 à F16) : fraude au RIB, usurpation, liquidation,
gel des avoirs, doublon, injection de prompt… Le détail de chaque piège est dans `crm/donnees_demo.py`.

## Installation manuelle (facultatif : le lanceur le fait tout seul)

```bash
python -m venv .venv
.venv\Scripts\activate               # macOS / Linux : source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env               # macOS / Linux : cp .env.example .env  (puis changer les 2 clés)
python -m pytest                     # 75 tests, sans réseau
```

Node.js (pour `npx`) est nécessaire pour le MCP Inspector : https://nodejs.org

## Organisation du dossier

```
OUVRIR_LES_SLIDES.cmd           ouvre la présentation
LANCER_MCP_INSPECTOR.cmd        lance le CRM + le MCP Inspector
diapos/                         les 6 slides (HTML/CSS/JS, fonctionnent hors ligne)
verif_fournisseur/
  mcp/serveur.py                le serveur MCP : déclare les 3 outils (aucune règle ici)
  outils/                       le code des 3 outils, un fichier chacun
    rechercher_entreprise.py      outil 1
    verifier_fournisseur.py       outil 2 (8 contrôles)
    traiter_factures_crm.py       outil 3 (lit le CRM, écrit le verdict)
    commun.py                     briques partagées (rapport, refus)
  regles.py                     TOUTES les règles et seuils
  identifiants.py               calculs locaux : SIRET, TVA, IBAN
  sources/                      1 fichier = 1 API publique (+ simulation.py : les 6 API simulées)
  crm_client.py · config.py     accès au CRM (clé MCP) · réglages lus dans .env
crm/                            le CRM de démo lu par traiter_factures_crm (FastAPI + SQLite)
tests/                          75 tests : chaque garde-fou est prouvé
docs/                           fiche de confiance, rapport de démo (16 factures sans / avec MCP), dossier Word
```

## Les 6 API (gratuites, sans clé)

Recherche d'entreprises (DINUM) · BODACC (DILA) · Géoplateforme (IGN) · Gels des avoirs (DG Trésor) ·
VATComply (relais VIES) · Frankfurter (taux BCE). Par défaut le serveur tourne en **mode simulation** (API simulées,
résultats reproductibles) ; `VERIF_MODE=reel` dans `.env` utilise les vraies API.

## Sécurité en bref

- Les règles sont dans le code (`regles.py`), jamais dans le prompt.
- Une source en panne ne donne jamais « aucune alerte » (fail-closed).
- La seule clé est celle du CRM, dans `.env` : l'IA ne la voit jamais, elle ne permet que d'écrire un verdict.
- Le texte d'une facture est une donnée, jamais une instruction (anti-injection de prompt).
- Aucune donnée personnelle (dirigeants) ne sort du serveur.
