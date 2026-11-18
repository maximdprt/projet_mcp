@echo off
REM Lance le MCP Inspector officiel, branche sur le serveur MCP Verif Fournisseur (3 outils).
REM Premier lancement : installe tout seul l'environnement Python et cree le .env (1 a 2 minutes).
REM Ensuite : demarre le CRM de demo (port 8000) puis ouvre l'Inspector : Connect, Tools, List Tools, Run Tool.
setlocal
cd /d "%~dp0"

REM --- 1. Environnement Python (.venv) -------------------------------------------------
if exist ".venv\Scripts\python.exe" goto venv_ok
echo Premiere utilisation : creation de l'environnement Python...
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo ERREUR : Python 3.10 ou plus recent est introuvable.
  echo Installez-le depuis https://www.python.org/downloads/ en cochant "Add python.exe to PATH", puis relancez.
  pause
  exit /b 1
)
:venv_ok
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo ERREUR : il faut Python 3.10 ou plus recent. Supprimez le dossier .venv, installez un Python recent, relancez.
  pause
  exit /b 1
)

REM --- 2. Dependances (installees seulement si elles manquent) -------------------------
".venv\Scripts\python.exe" -c "import mcp.server.mcpserver, fastapi, uvicorn, httpx, dotenv" >nul 2>nul
if not errorlevel 1 goto deps_ok
echo Installation des dependances Python...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo ERREUR : l'installation des dependances a echoue. Verifiez la connexion Internet et relancez.
  pause
  exit /b 1
)
:deps_ok

REM --- 3. Fichier .env (cles du CRM de demo) -------------------------------------------
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Fichier .env cree a partir de .env.example.
)

REM --- 4. Node.js (pour npx) -------------------------------------------------------------
where npx >nul 2>nul
if errorlevel 1 (
  echo ERREUR : Node.js est introuvable. Installez-le depuis https://nodejs.org puis relancez.
  pause
  exit /b 1
)

REM --- 5. CRM de demo (necessaire a traiter_factures_crm) ---------------------------------
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul
if errorlevel 1 (
  echo Demarrage du CRM de demo sur http://127.0.0.1:8000 ...
  start "CRM Verif Fournisseur" /min ".venv\Scripts\python.exe" -m uvicorn crm.app:app --port 8000
) else (
  echo CRM deja lance sur le port 8000.
)

REM --- 6. MCP Inspector ------------------------------------------------------------------
echo Ouverture du MCP Inspector : cliquez sur Connect, puis Tools, List Tools.
npx -y @modelcontextprotocol/inspector -e VERIF_MODE=simulation -e PYTHONPATH="%CD%" -e PYTHONIOENCODING=utf-8 "%CD%\.venv\Scripts\python.exe" -m verif_fournisseur.mcp.serveur
