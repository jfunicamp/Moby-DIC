@echo off
rem Builds the Moby-DIC executable in dist\Moby-DIC\ and a ZIP for distribution.
rem Gera o executavel do Moby-DIC em dist\Moby-DIC\ e um ZIP para distribuicao.
cd /d "%~dp0\.."
set PY=.venv\Scripts\python.exe
if not exist %PY% (
  echo .venv not found. Create it with: py -3.12 -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-extra.txt
  exit /b 1
)
%PY% empacotamento\gerar_icone.py || exit /b 1
rem HTML documentation (docs\html), bundled in the executable and opened by the Documentation button
%PY% docs\build_docs.py || exit /b 1
%PY% -m PyInstaller empacotamento\moby-dic.spec --distpath dist --workpath build_tmp --noconfirm || exit /b 1
for /f %%v in ('%PY% -c "import mobydic; print(mobydic.__version__)"') do set VER=%%v
copy /y LICENSE dist\Moby-DIC\LICENSE.txt >nul
copy /y THIRD_PARTY_NOTICES.md dist\Moby-DIC\THIRD_PARTY_NOTICES.md >nul
copy /y README.md dist\Moby-DIC\README.md >nul
if exist docs\video\Moby-DIC-tutorial.mp4 copy /y docs\video\Moby-DIC-tutorial.mp4 dist\Moby-DIC\Moby-DIC-tutorial.mp4 >nul
if exist docs\video\Moby-DIC-tutorial.srt copy /y docs\video\Moby-DIC-tutorial.srt dist\Moby-DIC\Moby-DIC-tutorial.srt >nul
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Moby-DIC' -DestinationPath 'dist\Moby-DIC-%VER%-windows-x64.zip' -Force"
echo.
echo Done: dist\Moby-DIC\Moby-DIC.exe  and  dist\Moby-DIC-%VER%-windows-x64.zip
