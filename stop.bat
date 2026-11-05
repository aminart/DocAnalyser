@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Arret DocAnalyser

echo ============================================================
echo   Arret de DocAnalyser : port 8020
echo ============================================================
echo.

rem Processus qui ecoutent reellement sur les ports, arretes avec leurs processus enfants
rem dont le processus de travail d'uvicorn en mode --reload. Detection independante de la langue de Windows.
powershell -NoProfile -Command ^
  "$pids = Get-NetTCPConnection -LocalPort 8020 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique;" ^
  "if (-not $pids) { Write-Host '[INFO] Aucun serveur actif sur le port 8020.'; exit 0 };" ^
  "foreach ($p in $pids) { Write-Host ('Arret du processus ' + $p + '...'); taskkill /T /F /PID $p | Out-Null };" ^
  "Write-Host '[OK] Serveurs arretes.'"

echo.
timeout /t 3 >nul
endlocal
