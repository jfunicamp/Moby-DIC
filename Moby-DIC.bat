@echo off
rem Abre o Moby-DIC a partir do codigo-fonte (requer o ambiente .venv).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m mobydic %*
