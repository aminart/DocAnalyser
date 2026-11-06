@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title DocAnalyser

rem Le backend sert aussi l'interface compilee : une seule fenetre, une seule adresse.
rem Node.js n'est necessaire que pour compiler l'interface, absente ou plus ancienne que ses sources.
rem
rem Remarque : pas de parentheses dans les messages, et pas de blocs if ( ... ) contenant des echo :
rem une parenthese dans un message ferme le bloc et fait planter le script.

cd /d "%~dp0"
set "ROOT=%~dp0"
set "VENV_PY=%ROOT%backend\.venv\Scripts\python.exe"

echo ============================================================
echo   Lancement de l'application DocAnalyser
echo ============================================================
echo.

rem ---------------------------------------------------------------- 1. Python
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
"%VENV_PY%" -c "import fastapi, uvicorn, multipart, pydantic_settings, httpx, fitz, docx, openpyxl, pptx, fpdf, cryptography" >nul 2>&1
if not errorlevel 1 goto :deps_ready
echo [1/3] Installation des dependances Python, cela peut prendre quelques minutes...
"%VENV_PY%" -m pip install --upgrade pip --quiet
"%VENV_PY%" -m pip install -r "%ROOT%backend\requirements.txt"
if errorlevel 1 goto :pip_failed
:deps_ready
echo [OK] Environnement Python pret : backend\.venv

rem ---------------------------------------------------------------- 2. Configuration
if exist "%ROOT%backend\.env" goto :env_ready
if not exist "%ROOT%backend\.env.example" goto :env_ready
copy "%ROOT%backend\.env.example" "%ROOT%backend\.env" >nul
echo [INFO] backend\.env cree a partir de backend\.env.example : renseignez-y vos modeles et cles.
:env_ready

rem ---------------------------------------------------------------- 3. Interface compilee
if not exist "%ROOT%frontend\dist\index.html" goto :build_front
rem Recompilation si une source de l'interface est plus recente que la version compilee, par exemple apres une mise a jour.
powershell -NoProfile -Command "$d = (Get-Item -LiteralPath '%ROOT%frontend\dist\index.html').LastWriteTime; $s = Get-ChildItem -LiteralPath '%ROOT%frontend\src','%ROOT%frontend\index.html','%ROOT%frontend\package.json' -Recurse -File | Where-Object { $_.LastWriteTime -gt $d }; if ($s) { exit 1 } else { exit 0 }"
if errorlevel 1 goto :build_front
goto :front_ready

:build_front
where npm >nul 2>&1
if errorlevel 1 goto :no_node
pushd "%ROOT%frontend"
if exist "node_modules\.bin\vite.cmd" goto :front_deps_ready
echo [3/3] Installation des dependances de l'interface : npm install...
call npm install
if errorlevel 1 goto :npm_failed_pop
:front_deps_ready
echo [3/3] Compilation de l'interface : npm run build...
call npm run build
if errorlevel 1 goto :build_failed_pop
popd
:front_ready
echo [OK] Interface prete : frontend\dist

rem ---------------------------------------------------------------- 4. Lancement
echo.
echo ============================================================
echo   DocAnalyser : http://127.0.0.1:8020
echo   Gardez cette fenetre ouverte ; fermez-la ou faites Ctrl+C pour arreter.
echo ============================================================
echo.
"%VENV_PY%" "%ROOT%backend\launcher.py" %*
if errorlevel 2 goto :port_busy
goto :end

rem ---------------------------------------------------------------- Erreurs
:no_node
echo [ERREUR] L'interface doit etre compilee, mais Node.js et npm sont introuvables.
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

:npm_failed_pop
popd
echo [ERREUR] npm install a echoue dans le dossier frontend : voir les messages ci-dessus.
goto :fail

:build_failed_pop
popd
echo [ERREUR] La compilation de l'interface a echoue : voir les messages ci-dessus.
goto :fail

:port_busy
echo [ERREUR] Le port 8020 est deja utilise par une autre application.
echo Si c'est un ancien lancement de DocAnalyser, lancez stop.bat puis relancez start.bat.
goto :fail

:fail
echo.
pause
exit /b 1

:end
endlocal
