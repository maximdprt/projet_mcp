"""Testeur MCP en terminal : se connecte au serveur Vérif Fournisseur comme le ferait une IA (Claude, Cursor).

Lancement (depuis la racine du projet) :
    python scripts/tester_mcp.py            menu interactif : lister les outils, en appeler un
    python scripts/tester_mcp.py --demo     démo automatique : 3 appels représentatifs

Ce que l'on voit : la connexion (transport stdio, poignée de main `initialize`), la liste des outils
(`tools/list`) avec leurs paramètres et annotations, puis chaque appel (`tools/call`) et la réponse du serveur.
`traiter_factures_crm` a besoin du CRM lancé (uvicorn crm.app:app --port 8000).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RACINE = Path(__file__).resolve().parents[1]
for flux in (sys.stdout, sys.stderr):       # console Windows : accents et symboles en UTF-8
    try:
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Couleurs ANSI (désactivées si le terminal ne les gère pas)
COULEUR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None
if os.name == "nt":
    os.system("")      # active les séquences ANSI dans la console Windows


def c(texte: str, code: str) -> str:
    return f"\033[{code}m{texte}\033[0m" if COULEUR else texte


GRIS, GRAS, BLEU, VERT, ROUGE, ORANGE, VIOLET = "90", "1", "94", "92", "91", "93", "95"
STATUTS = {"BLOQUER_LE_PAIEMENT": ROUGE, "VERIFICATION_HUMAINE_REQUISE": ORANGE,
           "AUCUNE_ALERTE_DETECTEE": VERT, "IMPOSSIBLE_DE_VERIFIER": VIOLET}

DEMO = [
    ("verifier_fournisseur", {"siret": "90123456700013", "nom_sur_facture": "ATELIER MERCIER",
                              "iban": "FR7630004000031234567890143", "tva": "FR15901234567",
                              "adresse": "45 cours Gambetta 69003 Lyon", "montant": "4180.00"},
     "Fournisseur sain : aucune alerte attendue"),
    ("verifier_fournisseur", {"siret": "90567891800012", "nom_sur_facture": "GLOBAL TRADING HOLDING",
                              "montant": "18750.00"},
     "Entité sous gel des avoirs : paiement bloqué"),
    ("verifier_fournisseur", {"siret": "13002526500014", "nom_sur_facture": "DINUM"},
     "SIRET à clé fausse : refusé sans aucun appel réseau"),
]


def titre(texte: str) -> None:
    print("\n" + c("━" * 72, GRIS) + "\n" + c(texte, GRAS) + "\n" + c("━" * 72, GRIS))


def parametres() -> StdioServerParameters:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(RACINE)}
    env.setdefault("VERIF_MODE", "simulation")
    return StdioServerParameters(command=sys.executable, args=["-m", "verif_fournisseur.server"],
                                 cwd=str(RACINE), env=env)


def afficher_outils(outils) -> None:
    titre(f"tools/list → {len(outils)} outils exposés par le serveur")
    for i, o in enumerate(outils, 1):
        a = o.annotations
        nature = "lecture seule" if a and a.read_only_hint else "écrit (verdict + journal uniquement)"
        print(f"\n {c(str(i), BLEU)}. {c(o.name, GRAS)}  {c('· ' + nature, GRIS)}")
        print("    " + (o.description or "").split("\n")[0][:110])
        schema = o.input_schema or {}
        requis = set(schema.get("required", []))
        for nom, prop in schema.get("properties", {}).items():
            obligatoire = c("obligatoire", ORANGE) if nom in requis else c("facultatif", GRIS)
            print(f"      - {nom} ({obligatoire})")


def afficher_resultat(resultat, duree_ms: int) -> None:
    donnees = resultat.structured_content
    if donnees is None and resultat.content:
        try:
            donnees = json.loads(resultat.content[0].text)
        except (ValueError, AttributeError):
            donnees = {"texte": getattr(resultat.content[0], "text", "")}
    print(c(f"\n← réponse en {duree_ms} ms" + ("  (erreur)" if resultat.is_error else ""), GRIS))
    if isinstance(donnees, dict):
        statut = donnees.get("statut")
        if statut:
            print("   statut  : " + c(statut, STATUTS.get(statut, GRAS) + ";1"))
        if donnees.get("message"):
            print("   message : " + str(donnees["message"]))
        for a in donnees.get("alertes", []) or []:
            couleur = ROUGE if a.get("niveau") == "BLOQUANT" else ORANGE if a.get("niveau") == "A_VERIFIER" else GRIS
            print(f"   {c('●', couleur)} {a.get('code')} — {a.get('message', '')[:100]}")
        for k in ("controles",):
            if donnees.get(k):
                ok = sum(1 for x in donnees[k] if x.get("resultat") == "OK")
                print(c(f"   contrôles : {ok}/{len(donnees[k])} OK", GRIS))
    print(c("\n   JSON complet :", GRIS))
    print(c(json.dumps(donnees, ensure_ascii=False, indent=2)[:3000], GRIS))


async def appeler(session: ClientSession, outil: str, arguments: dict) -> None:
    print("\n" + c("→ tools/call ", BLEU) + c(outil, GRAS) + " " + json.dumps(arguments, ensure_ascii=False))
    debut = time.monotonic()
    resultat = await session.call_tool(outil, arguments)
    afficher_resultat(resultat, int((time.monotonic() - debut) * 1000))


def demander_arguments(outil) -> dict:
    schema = outil.input_schema or {}
    requis = set(schema.get("required", []))
    arguments = {}
    print(c("  (Entrée vide = paramètre facultatif ignoré)", GRIS))
    for nom in schema.get("properties", {}):
        valeur = input(f"  {nom}{' *' if nom in requis else ''} : ").strip()
        if valeur:
            arguments[nom] = valeur
    return arguments


async def principal(demo: bool) -> None:
    titre("Connexion au serveur MCP « verif-fournisseur » (transport stdio)")
    print(c(f"  commande : {sys.executable} -m verif_fournisseur.server", GRIS))
    async with stdio_client(parametres()) as (lecture, ecriture):
        async with ClientSession(lecture, ecriture) as session:
            debut = time.monotonic()
            init = await session.initialize()
            info = init.server_info
            print(f"  {c('✓ connecté', VERT)} à {c(info.name, GRAS)} v{info.version} "
                  f"· protocole MCP {init.protocol_version} · {int((time.monotonic() - debut) * 1000)} ms")
            print(c(f"  mode : {os.environ.get('VERIF_MODE', 'simulation')} (API simulées si « simulation »)", GRIS))
            outils = (await session.list_tools()).tools
            afficher_outils(outils)

            if demo:
                for outil, arguments, explication in DEMO:
                    titre(explication)
                    await appeler(session, outil, arguments)
                return

            while True:
                print("\n" + c("Choisir un outil (numéro), « l » pour relister, « q » pour quitter.", BLEU))
                choix = input("> ").strip().lower()
                if choix in ("q", "quit", "exit"):
                    break
                if choix == "l":
                    afficher_outils(outils)
                    continue
                if not choix.isdigit() or not 1 <= int(choix) <= len(outils):
                    print(c("  Choix invalide.", ROUGE))
                    continue
                outil = outils[int(choix) - 1]
                titre(f"Appel de {outil.name}")
                try:
                    await appeler(session, outil.name, demander_arguments(outil))
                except Exception as e:      # erreur de protocole ou serveur : on l'affiche et on continue
                    print(c(f"  Échec de l'appel : {type(e).__name__}: {e}", ROUGE))


if __name__ == "__main__":
    try:
        asyncio.run(principal("--demo" in sys.argv))
    except (KeyboardInterrupt, EOFError):
        print("\nAu revoir.")
