@echo off
title Modo Bot
cd /d "%~dp0"
if not exist node_modules (
  echo Installation des dependances...
  call npm install
)
:start
node index.js
echo.
echo Le bot s'est arrete. Redemarrage dans 5 secondes... (ferme la fenetre pour arreter)
timeout /t 5 >nul
goto start
