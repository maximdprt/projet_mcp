# Démo : 16 factures, sans puis avec le MCP Vérif Fournisseur

Mode **simulation** : API simulées, entreprises fictives, résultat reproductible.

| Facture | Piège | Montant | Sans MCP | Avec MCP | Alertes du MCP |
|---|---|---|---|---|---|
| F01 | Facture saine d'un fournisseur habituel. | 4 180.00 € | 💸 payée | ✅ vérifiée | `—` |
| F02 | Fraude au changement de RIB : nouvel IBAN à l'étranger. | 4 180.00 € | 💸 payée | ⛔ bloquée | `IBAN_ETRANGER, IBAN_DIFFERENT_DU_REFERENTIEL` |
| F03 | SIRET mal recopié ou inventé (un chiffre change). | 4 180.00 € | 💸 payée | ⛔ bloquée | `SIRET_INVALIDE, SIRET_DIFFERENT_DU_REFERENTIEL` |
| F04 | Usurpation : le nom d'un fournisseur connu avec le SIRET d'une autre société. | 4 180.00 € | 💸 payée | ⛔ bloquée | `TVA_INCOHERENTE, ENTREPRISE_RECENTE, NOM_DIFFERENT, ADRESSE_DIFFERENTE, SIRET_DIFFERENT_DU_REFERENTIEL, IBAN_DIFFERENT_DU_REFERENTIEL` |
| F05 | Fournisseur en liquidation judiciaire : le paiement doit aller au liquidateur. | 2 450.00 € | 💸 payée | ⛔ bloquée | `LIQUIDATION_JUDICIAIRE` |
| F06 | Entreprise cessée depuis 2025 qui facture encore. | 1 950.00 € | 💸 payée | ⛔ bloquée | `ENTREPRISE_CESSEE, ETABLISSEMENT_FERME, RADIATION_PUBLIEE, TVA_NON_ENREGISTREE_VIES` |
| F07 | Entité inscrite au registre national des gels des avoirs. | 18 750.00 € | 💸 payée | ⛔ bloquée | `GEL_DES_AVOIRS, DOUBLE_VALIDATION` |
| F08 | Numéro de TVA d'une autre entreprise. | 4 180.00 € | 💸 payée | ⛔ bloquée | `TVA_INCOHERENTE` |
| F09 | Montant 11 fois supérieur à l'habitude. | 48 500.00 € | 💸 payée | 🟠 contrôle humain | `DOUBLE_VALIDATION, MONTANT_ANORMAL` |
| F10 | Doublon : même numéro qu'une facture déjà payée. | 4 050.00 € | 💸 payée | ⛔ bloquée | `DOUBLON_FACTURE` |
| F11 | Fournisseur en redressement judiciaire. | 5 800.00 € | 💸 payée | 🟠 contrôle humain | `PROCEDURE_COLLECTIVE` |
| F12 | Facture saine en dollars : conversion au taux BCE par le serveur. | 4 140.00 € | 💸 payée | ✅ vérifiée | `—` |
| F13 | Adresse de facturation inexistante. | 4 180.00 € | 💸 payée | 🟠 contrôle humain | `ADRESSE_INTROUVABLE` |
| F14 | Société créée il y a 40 jours (schéma classique des sociétés éphémères). | 3 200.00 € | 💸 payée | 🟠 contrôle humain | `ENTREPRISE_RECENTE` |
| F15 | Injection de prompt cachée dans la facture + RIB modifié. | 4 180.00 € | 💸 payée | ⛔ bloquée | `IBAN_DIFFERENT_DU_REFERENTIEL` |
| F16 | Premier paiement à un fournisseur absent du référentiel. | 2 900.00 € | 💸 payée | 🟠 contrôle humain | `FOURNISSEUR_INCONNU` |

## Bilan

- **Sans MCP** : 16 factures payées, dont **112 680.00 €** sur des factures frauduleuses ou anormales.
- **Avec MCP** : 112 680.00 € retenus sur 112 680.00 € exposés ; seules les factures saines passent en « vérifiée ».
- Résultat conforme à l'attendu pour **16/16** scénarios.
- Synthèse des statuts : `{'AUCUNE_ALERTE_DETECTEE': 2, 'BLOQUER_LE_PAIEMENT': 9, 'VERIFICATION_HUMAINE_REQUISE': 5}`
- Le MCP essaie de payer avec sa clé → HTTP **403** (refusé par le CRM).
- Un humain essaie de payer une facture bloquée → HTTP **409** (refusé).
- Un humain paie une facture vérifiée → HTTP **200** (accepté).
