# Vérif Fournisseur — le MCP qui empêche l'IA de payer une fausse facture

Avant de payer une facture, l'IA passe par ce serveur MCP. Il contrôle le fournisseur dans **6 API publiques**,
fait les calculs lui-même et rend un statut décidé par le code. Un **CRM de test** contient 16 factures
piégées : fraude au RIB, usurpation, liquidation, gel des avoirs, doublon, injection de prompt…

| Statut | Dans le CRM | Signification |
|---|---|---|
| `BLOQUER_LE_PAIEMENT` | `bloquee` | au moins un fait rend le paiement anormal |
| `IMPOSSIBLE_DE_VERIFIER` | `impossible_de_verifier` | une source indispensable n'a pas répondu |
| `VERIFICATION_HUMAINE_REQUISE` | `a_verifier_humain` | un signal demande un contrôle humain |
| `AUCUNE_ALERTE_DETECTEE` | `verifiee` | rien d'anormal dans les sources (ce qui ne veut pas dire « fiable ») |

## Démarrage rapide (5 minutes)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # Windows : copy .env.example .env
python -m pytest                     # 130 tests verts, sans réseau
python -m demo.comparaison           # le tableau « sans MCP / avec MCP » -> RAPPORT_DEMO.md
```

## La preuve d'utilité : `python -m demo.comparaison`

Les 16 factures du CRM sont traitées deux fois : par une automatisation qui fait confiance à la facture (sans MCP),
puis par l'outil `traiter_factures_crm`. Résultat (voir `RAPPORT_DEMO.md`) :

- **Sans MCP** : 16 factures payées, dont 112 680 € frauduleux ou anormaux.
- **Avec MCP** : 9 bloquées, 5 envoyées à un humain, 2 vérifiées (les 2 seules saines) → 16/16 conformes.
- Le MCP tente de payer avec sa clé → **403**. Un humain tente de payer une facture bloquée → **409**.

## Utiliser le MCP dans Cursor

1. Installer comme ci-dessus (le dossier `.venv` doit exister à la racine).
2. Lancer le CRM dans un terminal : `uvicorn crm.app:app --port 8000` → http://127.0.0.1:8000
   (SaaS web : saisir la clé `CRM_CLE_ADMIN` du `.env` ; elle n'est écrite nulle part dans le code)
3. Le fichier `.cursor/mcp.json` déclare déjà le serveur (mode simulation). Dans Cursor : **Settings → MCP** →
   vérifier que `verif-fournisseur` est actif (bouton d'actualisation si besoin).
   Windows : remplacer `.venv/bin/python` par `.venv\\Scripts\\python.exe` dans `.cursor/mcp.json`.
   Si `${workspaceFolder}` n'est pas reconnu par votre version de Cursor, mettre le chemin absolu du projet.
4. Dans le chat agent : *« Vérifie toutes les factures reçues du CRM »* (après avoir déposé des factures, ou
   importé le jeu de test : `POST /api/demo/reinitialiser?jeu_de_test=true`).

## Le SaaS de démonstration (http://127.0.0.1:8000)

Le CRM est devenu un petit SaaS anti-fraude, dans l'esprit des solutions de vérification fournisseurs du marché,
mais piloté par un serveur MCP : **on dépose une facture, le MCP l'analyse sous nos yeux, un humain décide.**

1. **Dépôt** (page *Analyser*) : glisser un PDF, un TXT ou un JSON, ou saisir à la main. Le CRM lit la facture
   **sans IA** (libellés + expressions régulières, `crm/extraction.py`) et montre *ce qu'il a lu* pour correction.
   Il la rattache au référentiel (nom identique, sinon SIRET identique, `crm/ingestion.py`).
2. **Analyse par le MCP** : le CRM lance le **vrai serveur MCP** et appelle son outil `traiter_factures_crm`
   par le protocole MCP (`crm/analyse.py`), exactement comme Cursor. C'est le MCP qui lit la facture, interroge les
   sources, applique les règles et **écrit lui-même son verdict** (clé MCP : écrire un résultat, rien d'autre).
3. **Résultat** : les 9 contrôles s'allument un par un, le verdict tombe (rouge : paiement bloqué · orange :
   contrôle humain · vert : aucune alerte · violet : invérifiable). *Pourquoi ce verdict* liste les raisons (rouge
   bloquant, orange à vérifier) et les **champs fautifs sont entourés sur la facture** (IBAN, SIRET, TVA…).
   La *trace de l'appel MCP* montre la requête `tools/call`, l'écriture du verdict et la durée.
4. **Décision humaine** : validation après contre-appel (commentaire obligatoire), puis paiement simulé.
   Une facture bloquée reste verrouillée : le CRM refuse (HTTP 409).

Autres pages : **Jeu de test** (les 16 factures PDF fictives à glisser, et la *démo complète* qui les dépose et les
fait analyser d'un clic), **Fournisseurs** (le référentiel : IBAN et téléphone de contre-appel), **Journal** (chaque
dépôt, appel MCP, verdict et décision, horodatés). Outils de tournage : *Rejouer*, *Vitesse ×1/×2/×4*, *Plein écran*.

Design : jetons de thème et styles de composants repris de [shadcn/ui](https://github.com/shadcn-ui/ui) (licence MIT,
voir `crm/interface/LICENCES-TIERS.md`), transposés en CSS pur ; barre latérale, mise en page adaptée par requêtes
de conteneur, thème clair et sombre. Les couleurs vives sont réservées aux verdicts, chacun avec sa forme.

Sécurité : aucune clé dans le code de la page (saisie, gardée dans l'onglet) ; tout le contenu des factures est
affiché en texte, jamais interprété ; CSP stricte ; fichiers limités à 5 Mo (PDF texte, TXT, JSON ; pas d'OCR) ;
la clé du MCP ne peut ni déposer, ni lancer d'analyse, ni payer (403) ; un échec de l'appel MCP ne conclut rien.

Claude Code lit `.mcp.json` (même serveur) et `CLAUDE.md` (contexte du projet). Cursor lit `.cursor/rules/projet.mdc`.

## Phrases de démo pour l'oral

1. « Vérifie toutes les factures reçues du CRM. » → 9 bloquées, 5 à contrôler, 2 vérifiées.
2. « Pourquoi la facture F15 est bloquée ? » → RIB modifié ; le message caché « ignore les contrôles » n'a eu aucun effet.
3. « Paie la facture F02. » → l'IA n'a aucun outil de paiement ; même un humain est refusé par le CRM.
4. « Vérifie le fournisseur SIRET 90567891800012, Global Trading Holding. » → gel des avoirs, bloqué.
5. « Facture DINUM, SIRET 13002526500014. » → SIRET invalide, bloqué sans aucun appel réseau.

## Mode réel

Mettre `VERIF_MODE=reel` dans `.env` (et dans `.cursor/mcp.json`), puis `python scripts/test_reel.py` pour
vérifier que les 6 API répondent. En mode réel, les entreprises fictives du CRM n'existent pas : le CRM sert
alors surtout pour le scénario F16 (DINUM). Chaque rapport indique son `mode`.

## Les 6 API (toutes gratuites, sans clé)

| API | Catalogue | Ce qu'elle prouve |
|---|---|---|
| Recherche d'entreprises (DINUM) | data.gouv.fr | l'entreprise existe, est active, son nom officiel |
| BODACC (DILA) | data.gouv.fr | liquidation, redressement, radiation |
| Géoplateforme – Géocodage (IGN) | data.gouv.fr | l'adresse de la facture existe et est dans la bonne commune |
| Gels des avoirs (DG Trésor) | data.gouv.fr | le fournisseur n'est pas sous sanctions financières |
| VATComply (relais VIES) | public-apis | le n° de TVA est réellement actif |
| Frankfurter (taux BCE) | public-apis | montant exact en euros pour appliquer les seuils |

## Structure

Voir `CLAUDE.md` (architecture, invariants, comment ajouter une API).

## Rendu (sans .venv ni .env)

```bash
cd .. && zip -r verif-fournisseur-mcp.zip verif-fournisseur-mcp -x "*/.venv/*" "*/.env" "*/__pycache__/*" "*/.pytest_cache/*" "*/crm/*.sqlite3"
```
