@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "PYTHON_EXE="

cd /d "%ROOT_DIR%"

py -3.10 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYTHON_EXE=py -3.10"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo Using Python:
%PYTHON_EXE% -c "import sys; print(sys.executable); print(sys.version)"
if errorlevel 1 goto :fail

echo Creating .venv310...
%PYTHON_EXE% -m venv .venv310
if errorlevel 1 goto :fail

echo Upgrading pip...
".venv310\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo Installing Translate Manga V2 dependencies...
".venv310\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo Installing Saber-Translator CPU dependencies...
".venv310\Scripts\python.exe" -m pip install -r "vendor\Saber-Translator\requirements-cpu.txt"
if errorlevel 1 goto :fail

echo.
echo Setup finished.
echo Next:
echo   1. Copy config\local.example.json to config\local.json
echo   2. Fill translation.base_url and translation.api_key
echo   3. Run start_cli.bat
echo.
if "%TRANSLATE_MANGA_NO_PAUSE%"=="" pause
exit /b 0

:fail
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Setup failed with exit code %EXIT_CODE%.
echo Please check Python installation and network connection.
echo.
if "%TRANSLATE_MANGA_NO_PAUSE%"=="" pause
exit /b %EXIT_CODE%
