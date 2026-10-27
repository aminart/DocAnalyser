@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Analyse documentaire

rem Remarque : pas de parentheses dans les messages, et pas de blocs if ( ... ) contenant des echo :
rem une parenthese dans un message ferme le bloc et fait planter le script.

cd /d "%~dp0"
set "ROOT=%~dp0"
set "VENV_PY=%ROOT%backend\.venv\Scripts\python.exe"

echo ============================================================
echo   Lancement de l'application Analyse documentaire
echo ============================================================
echo.

rem ---------------------------------------------------------------- 1. Node.js
where npm >nul 2>&1
if errorlevel 1 goto :no_node

rem ---------------------------------------------------------------- 2. Python
if exist "%VENV_PY%" goto :venv_ready

echo [1/3] Creation de l'environnement Python backend\.venv...
set "PYTHON_CMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3"
if defined PYTHON_CMD goto :create_venv
python --version >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"
if not defined PYTHON_CMD goto :no_python

:create_venv
!PYTHON_CMD! -m venv "%ROOT%backend\.venv"
if errorlevel 1 goto :venv_failed

:venv_ready
"%VENV_PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 goto :python_too_old

rem Dependances completes ? Sinon installation ou complement.
"%VENV_PY%" -c "import fastapi, uvicorn, multipart, pydantic_settings, httpx, fitz, docx, openpyxl, pptx, fpdf" >nul 2>&1
if not errorlevel 1 goto :deps_ready
echo [1/3] Installation des dependances Python, cela peut prendre quelques minutes...
"%VENV_PY%" -m pip install --upgrade pip --quiet
"%VENV_PY%" -m pip install -r "%ROOT%backend\requirements.txt"
if errorlevel 1 goto :pip_failed
:deps_ready
echo [OK] Environnement Python pret : backend\.venv

rem ---------------------------------------------------------------- 3. Configuration
if exist "%ROOT%backend\.env" goto :env_ready
if not exist "%ROOT%backend\.env.example" goto :env_ready
copy "%ROOT%backend\.env.example" "%ROOT%backend\.env" >nul
echo [INFO] backend\.env cree a partir de backend\.env.example : renseignez-y vos modeles et cles.
:env_ready

rem ---------------------------------------------------------------- 4. Frontend
if exist "%ROOT%frontend\node_modules\.bin\vite.cmd" goto :front_ready
echo [2/3] Installation des dependances frontend : npm install...
pushd "%ROOT%frontend"
call npm install
set "NPM_RC=!errorlevel!"
popd
if not "!NPM_RC!"=="0" goto :npm_failed
:front_ready
echo [OK] Dependances frontend pretes

echo.
echo ============================================================
echo   Demarrage des services
echo ============================================================
echo.

rem ---------------------------------------------------------------- 5. Backend
rem Detection par PowerShell : netstat affiche des etats traduits selon la langue de Windows.
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 goto :backend_running

echo [3/3] Demarrage du backend sur http://localhost:8000 dans une nouvelle fenetre...
rem La fenetre reste ouverte en cas d'erreur pour pouvoir la lire.
start "Analyse documentaire - Backend" /d "%ROOT%backend" cmd /k ""%VENV_PY%" -m uvicorn app.main:app --reload --port 8000"

echo Attente du backend...
powershell -NoProfile -Command "for ($i = 0; $i -lt 60; $i++) { try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8000/health | Out-Null; exit 0 } catch { Start-Sleep -Milliseconds 500 } }; exit 1"
if errorlevel 1 echo [ATTENTION] Le backend ne repond pas encore : consultez la fenetre Backend en cas d'erreur.
goto :start_frontend

:backend_running
echo [OK] Un backend est deja actif sur le port 8000. Pour le redemarrer, lancez stop.bat puis start.bat.

rem ---------------------------------------------------------------- 6. Frontend
:start_frontend
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 goto :front_busy

rem Ouverture du navigateur quelques secondes apres le demarrage de Vite.
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process 'http://localhost:5173'"

echo.
echo [Frontend] Demarrage sur http://localhost:5173
echo Pour arreter : Ctrl+C ici puis fermez la fenetre Backend, ou lancez stop.bat.
echo.
pushd "%ROOT%frontend"
call npm run dev -- --port 5173 --strictPort
popd
goto :end

rem ---------------------------------------------------------------- Erreurs
:no_node
echo [ERREUR] Node.js et npm sont introuvables.
echo Installez Node.js, version LTS, depuis https://nodejs.org/ puis relancez start.bat.
goto :fail

:no_python
echo [ERREUR] Python est introuvable.
echo Installez Python 3.10 ou plus recent depuis https://www.python.org/
echo Cochez "Add python.exe to PATH" pendant l'installation, puis relancez start.bat.
goto :fail

:venv_failed
echo [ERREUR] Impossible de creer l'environnement Python backend\.venv.
goto :fail

:python_too_old
echo [ERREUR] La version de Python de backend\.venv est trop ancienne : 3.9 minimum.
echo Supprimez le dossier backend\.venv, installez un Python recent, puis relancez start.bat.
goto :fail

:pip_failed
echo [ERREUR] L'installation des dependances Python a echoue : voir les messages ci-dessus.
echo Derriere un proxy d'entreprise, configurez pip ou demandez l'acces a pypi.org.
goto :fail

:npm_failed
echo [ERREUR] npm install a echoue dans le dossier frontend : voir les messages ci-dessus.
goto :fail

:front_busy
echo [ERREUR] Le port 5173 est deja utilise, sans doute par un ancien lancement.
echo Lancez stop.bat puis relancez start.bat.
goto :fail

:fail
echo.
pause
exit /b 1

:end
endlocal
