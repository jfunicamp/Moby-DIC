@echo off
rem Moby-DIC from source. On the first run it creates the Python environment (.venv) and installs
rem the dependencies (a few minutes, needs internet). Requires Python 3.10-3.12 (python.org).
rem Abre o Moby-DIC a partir do codigo-fonte. Na primeira vez cria o ambiente .venv e instala as
rem dependencias (alguns minutos, precisa de internet). Requer Python 3.10-3.12 (python.org).
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if exist "%PY%" goto rodar

echo Moby-DIC: first run - creating the Python environment (.venv) ...
set BASE=
py -3.12 -c "import sys" >nul 2>&1 && set BASE=py -3.12
if not defined BASE py -3.11 -c "import sys" >nul 2>&1 && set BASE=py -3.11
if not defined BASE py -3.10 -c "import sys" >nul 2>&1 && set BASE=py -3.10
if not defined BASE python -c "import sys; sys.exit(not (3,10) <= sys.version_info[:2] <= (3,12))" >nul 2>&1 && set BASE=python
if not defined BASE (
  echo.
  echo Python 3.10, 3.11 or 3.12 was not found. Install Python 3.12 from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH"^), or use the Windows executable from the Releases page instead.
  echo Python 3.10-3.12 nao encontrado. Instale o Python 3.12 ou use o executavel da pagina Releases.
  goto erro
)
%BASE% -m venv .venv || goto erro
"%PY%" -m pip install --upgrade pip >nul
echo Installing dependencies / instalando dependencias ...
"%PY%" -m pip install -r requirements.txt || goto erro

:rodar
"%PY%" -m mobydic %*
if errorlevel 1 goto erro
exit /b 0

:erro
echo.
echo Moby-DIC could not start (see the messages above). / O Moby-DIC nao pode iniciar.
pause
exit /b 1
