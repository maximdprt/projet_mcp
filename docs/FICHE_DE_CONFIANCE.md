# Fiche de confiance — Vérif Fournisseur (MCP)

**Domaine : argent.** Avant de payer une facture, l'IA doit passer par ce MCP. Il contrôle le fournisseur dans 6 sources publiques et dans le CRM, puis rend un statut décidé par le code : `BLOQUER_LE_PAIEMENT`, `IMPOSSIBLE_DE_VERIFIER`, `VERIFICATION_HUMAINE_REQUISE` ou `AUCUNE_ALERTE_DETECTEE`.

**1. Pourquoi ce projet ?** La fraude au faux fournisseur et au changement de RIB vide la trésorerie des TPE et PME. Une IA qui traite des factures croit ce qui est écrit dessus : le nom, l'IBAN, et même un message caché qui lui ordonne de payer. Pour : les TPE et PME, les comptables, et les agents IA qui préparent des paiements.

**2. Pourquoi ces API ?** Elles sont toutes officielles ou adossées à une source officielle, gratuites, sans clé, et prises dans les catalogues fournis. Sur data.gouv.fr : **Recherche d'entreprises** (existence, état, nom officiel), **BODACC** (liquidations, radiations), **Géoplateforme** (l'adresse existe et se trouve dans la bonne commune) et **Gels des avoirs** (sanctions financières, paiement interdit). Dans public-apis : **VATComply**, qui relaie VIES (la TVA est-elle active ?), et **Frankfurter** (taux de la BCE, pour un montant exact en euros). Écartées : Pappers et Société.com (payants), l'API Sirene de l'INSEE (clé obligatoire), des services d'IBAN tiers non officiels.

**3. Pourquoi 3 outils ?** Un outil par intention. `rechercher_entreprise` sert quand on n'a qu'un nom. `verifier_fournisseur` sert quand on a une facture devant soi et lance 8 contrôles. `traiter_factures_crm` vérifie les factures du CRM et ajoute ce que seul le référentiel connaît : RIB différent de celui enregistré, doublon, montant anormal. La première version avait 5 outils : les fusionner empêche l'IA de ne faire qu'une vérification partielle. **Pas un de plus :** pas de « payer » ou « envoyer » (irréversible), pas de « dirigeants » (RGPD), pas de « score » (aucune source fiable). **Pas un de moins :** sans le CRM, la fraude au RIB, qui est la plus courante, reste invisible.

**4. Actions et refus.** Les outils **lisent, cherchent et calculent**. Ils n'**écrivent** qu'une chose : le résultat et une trace d'audit dans le CRM. Ils **refusent** de payer, de modifier un IBAN, de chercher un numéro dont la clé est fausse, de vérifier un paiement sur un nom seul, de choisir entre homonymes, de dire « fiable » et de conclure quand une source est en panne.

**5. Architecture.** IA → MCP (stdio, local) → 6 API + CRM. **Les règles sont dans le code** (`regles.py`) : l'IA ne fait que transmettre le statut. **La clé :** les API n'en ont pas. La seule clé est celle du CRM : elle est dans le `.env` du serveur, l'IA ne la voit jamais, et elle n'autorise qu'une action, enregistrer un résultat. Payer ou changer un IBAN demande la clé administrateur d'un humain (moindre privilège).

## Garde-fous → tests (130 tests, `python -m pytest`)

| Garde-fou | Test |
|---|---|
| SIRET dont la clé est fausse → bloqué, **0 appel réseau** | `test_G1_*` |
| SIREN exact uniquement ; « introuvable » ≠ « inexistante » | `test_G2_*`, `test_G8_*` |
| Panne d'une source essentielle → `IMPOSSIBLE_DE_VERIFIER` ; panne secondaire → humain | `test_G3_*` (3) |
| Aucune donnée personnelle ; textes externes nettoyés (anti-injection) | `test_G4_*`, `test_G12_*`, `test_injection_*` |
| Nom ≠ officiel → bloqué ; faute d'orthographe (imitation) → humain | `test_G5_*` |
| Cessée, liquidation, gel des avoirs, TVA d'un autre, IBAN faux → bloqué | `test_G6/7/13/15_*` |
| Redressement, entreprise récente, adresse fausse, montant ≥ seuil → humain | `test_G7/14/16/17_*` |
| 3 outils, aucun ne paie ; la clé du MCP est refusée par le CRM (403) ; clés MCP et admin identiques → le CRM refuse de démarrer | `test_G11_*`, `test_le_mcp_ne_peut_*`, `test_le_crm_refuse_de_demarrer_*` |
| RIB ≠ référentiel, doublon, montant 3× l'historique → bloqué ou humain | `test_scenario[F02…F16]` (16) |
| CRM ou API en panne → rien n'est écrit, la facture reste impayable | `test_crm_injoignable_*`, `test_api_externe_*` |
| SaaS : facture déposée lue sans IA, verdict écrit par le MCP lui-même ; fichier refusé (> 5 Mo, type, illisible) ; échec du MCP → rien n'est conclu ; la clé du MCP ne dépose ni ne lance rien (403) ; page sans clé ni HTML interprété (CSP) | `test_crm_saas.py` (51), `test_crm_interface.py` (21) |

**Preuve d'utilité** (`docs/RAPPORT_DEMO.md`) : sans MCP, 16 factures payées dont 112 680 € frauduleux ou anormaux. Avec MCP : 9 bloquées, 5 envoyées à un humain, et seules les 2 factures saines sont vérifiées (16/16 conformes).

**Limites assumées.** Le titulaire de l'IBAN n'est pas vérifiable : il faut contre-appeler au numéro du référentiel. Le BODACC peut avoir un délai de publication. Le registre des gels est mis en cache 6 h maximum. La comparaison des noms est une heuristique qui, en cas de doute, renvoie vers un humain. La démo tourne en mode simulation (entreprises fictives), et chaque rapport indique son mode.
