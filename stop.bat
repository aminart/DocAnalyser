@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Arret Analyse documentaire

echo ============================================================
echo   Arret des serveurs Analyse documentaire : ports 8000 et 5173
echo ============================================================
echo.

rem Processus qui ecoutent reellement sur les ports, arretes avec leurs processus enfants
rem dont le processus de travail d'uvicorn --reload. Detection independante de la langue de Windows.
powershell -NoProfile -Command ^
  "$pids = Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique;" ^
  "if (-not $pids) { Write-Host '[INFO] Aucun serveur actif sur les ports 8000 et 5173.'; exit 0 };" ^
  "foreach ($p in $pids) { Write-Host ('Arret du processus ' + $p + '...'); taskkill /T /F /PID $p | Out-Null };" ^
  "Write-Host '[OK] Serveurs arretes.'"

echo.
timeout /t 3 >nul
endlocal
