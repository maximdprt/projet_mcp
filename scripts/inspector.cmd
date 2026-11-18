@echo off
REM MCP Inspector officiel (Model Context Protocol) branche sur le serveur Verif Fournisseur.
REM Ouvre une page web : Connect, puis Tools > List Tools > choisir un outil > Run Tool.
REM traiter_factures_crm a besoin du CRM lance : uvicorn crm.app:app --port 8000
cd /d "%~dp0.."
npx -y @modelcontextprotocol/inspector -e VERIF_MODE=simulation -e PYTHONPATH="%CD%" -e PYTHONIOENCODING=utf-8 "%CD%\.venv\Scripts\python.exe" -m verif_fournisseur.server
