# CLAUDE.md — Vérif Fournisseur (MCP fiabilisé + CRM de test)

Projet étudiant : un serveur MCP qui empêche une IA de valider le paiement d'une facture frauduleuse ou anormale.
L'IA ne décide rien : elle appelle un outil, le serveur interroge 6 API publiques, applique des règles écrites
dans le code et renvoie un statut. Un CRM de test (FastAPI + SQLite) contient 16 factures piégées.

## Commandes

```bash
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt && cp .env.example .env
python -m pytest -v                 # 134 tests, hors ligne
python -m demo.comparaison          # démo sans/avec MCP -> RAPPORT_DEMO.md
uvicorn crm.app:app --port 8000     # SaaS : dépôt de factures + analyse MCP http://127.0.0.1:8000, API /docs
python -m verif_fournisseur.server  # serveur MCP (stdio) ; normalement lancé par Cursor / Claude
python scripts/test_reel.py         # contrôle des 6 vraies API (internet)
```

## Architecture

```
IA (Cursor, Claude Desktop…)
  │  MCP stdio — 3 outils
  ▼
verif_fournisseur/server.py        déclaration des outils + instructions à l'IA (aucune règle ici)
  └─ verifications.py              validation des entrées, enchaînement des 8 contrôles, conclusion
       ├─ regles.py                TOUTES les règles : statuts, seuils, noms, BODACC, règles CRM
       ├─ identifiants.py          calculs locaux : Luhn SIREN/SIRET, clé TVA, IBAN modulo 97
       ├─ sources/                 1 module = 1 API, liste blanche des champs, gestion des pannes
       │    entreprises.py  Recherche d'entreprises (DINUM)     data.gouv.fr
       │    bodacc.py       BODACC (DILA)                       data.gouv.fr
       │    adresse.py      Géoplateforme géocodage (IGN)       data.gouv.fr
       │    gels.py         Gels des avoirs (DG Trésor)         data.gouv.fr
       │    tva.py          VATComply (relais VIES)             public-apis
       │    change.py       Frankfurter (taux BCE)              public-apis
       ├─ crm_client.py            appels au CRM avec la clé CRM_CLE_MCP (lue dans .env)
       └─ simulation.py            les 6 API simulées (VERIF_MODE=simulation)
crm/app.py                         CRM : 2 clés (mcp / admin), refuse de payer ce qui n'est pas « verifiee »
crm/extraction.py                  lecture d'une facture déposée (PDF texte, TXT, JSON) : regex, sans IA
crm/ingestion.py                   enregistrement, rattachement au référentiel (nom puis SIRET), lien jeu de test
crm/analyse.py                     le CRM appelle le serveur MCP (stdio, outil traiter_factures_crm)
crm/pdf_factures.py                PDF fictifs du jeu de test (sans dépendance)
crm/interface/                     SaaS web (HTML/CSS/JS) : pitch (11 diapos, PITCH.md), dépôt, scène d'analyse, décision ;
                                   aucune clé, aucune règle. CRM_MODE_PRESENTATION=1 : page locale sans clé (en-tête X-Presentation)
crm/donnees_demo.py                fournisseurs, historique, 16 SCÉNARIOS (facture, piège, attendu)
demo/harnais.py                    branche MCP + API simulées + CRM dans un seul processus (tests, démo)
```

### Les 3 outils
| Outil | Quand | Écrit ? |
|---|---|---|
| `rechercher_entreprise(nom, code_postal?)` | on n'a qu'un nom | non |
| `verifier_fournisseur(siret, nom_sur_facture, iban?, tva?, adresse?, montant?, devise?)` | une facture devant soi | non |
| `traiter_factures_crm(facture_id?)` | factures du CRM (une, ou toutes les « recue ») | uniquement le résultat + journal |

### Les 8 contrôles de `verifier_fournisseur` (toujours dans cet ordre)
identifiants (local) → identite_entreprise → nom_facture (local) → procedures_bodacc → gel_des_avoirs →
tva_vies → adresse_facture → montant_eur. `traiter_factures_crm` ajoute `referentiel_crm`
(IBAN/SIRET ≠ référentiel, doublon, montant anormal vs historique, fournisseur inconnu).

Sources **essentielles** (panne ⇒ `IMPOSSIBLE_DE_VERIFIER`) : entreprises, BODACC, gels, change (si devise ≠ EUR).
Sources **secondaires** (panne ⇒ alerte `A_VERIFIER`) : VIES, géocodage.

### Statuts (regles.py) et statut CRM
`BLOQUER_LE_PAIEMENT`→`bloquee` · `IMPOSSIBLE_DE_VERIFIER`→`impossible_de_verifier` ·
`VERIFICATION_HUMAINE_REQUISE`→`a_verifier_humain` · `AUCUNE_ALERTE_DETECTEE`→`verifiee`.
Priorité : un BLOQUANT l'emporte sur tout ; puis panne ; puis A_VERIFIER ; sinon OK.

## Invariants — ne jamais casser
1. Les règles sont dans le code (`regles.py`, `verifications.py`), jamais dans le prompt ou les instructions.
2. Fail-closed : une panne ne produit jamais `AUCUNE_ALERTE_DETECTEE`.
3. Aucun outil ne paie, n'envoie, ni ne modifie un IBAN/fournisseur. La clé MCP du CRM n'en a pas le droit (403).
   Les deux clés du CRM doivent être différentes : sinon le CRM refuse de démarrer.
4. Montants en `Decimal`, arrondi au centime `ROUND_HALF_UP`. Jamais de float.
5. Aucune donnée personnelle en sortie : listes blanches dans `sources/` (dirigeants, mandataires exclus).
6. Correspondance EXACTE du SIREN (la recherche de l'API est floue).
7. Tout texte externe passe par `texte()` (nettoyé, tronqué) : c'est une donnée, pas une instruction.
8. Un SIRET à clé fausse est refusé avant tout appel réseau.
9. Chaque garde-fou a un test. `python -m pytest` reste vert. Nouveau scénario = une ligne dans `SCENARIOS`.

## Ajouter une API
1. `verif_fournisseur/sources/ma_source.py` : `SOURCE`, `URL`, une fonction async qui utilise `http.get_json`
   et renvoie un dict filtré par liste blanche ; lever `SourceIndisponible` si le format est inattendu.
2. Simuler l'hôte dans `simulation.gestionnaire`.
3. Ajouter le contrôle dans `verifier_fournisseur` (essentiel ou secondaire) et ses alertes dans `regles.py`.
4. Tests : cas OK, cas d'alerte, panne. Mettre à jour la fiche de confiance.

## Conventions
Français partout (code, messages, commits). Codes d'alerte en MAJUSCULES_SNAKE. Les entreprises de la simulation
sont fictives mais leurs numéros respectent les clés de contrôle.

## Idées pour la suite
OCR des factures scannées · file d'attente des contre-appels · export du journal d'audit · transport HTTP du MCP avec authentification.
