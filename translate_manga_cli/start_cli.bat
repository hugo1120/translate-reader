@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "APP_ENTRY=%ROOT_DIR%batch_translate.py"
set "LOCAL_VENV310=%ROOT_DIR%.venv310\Scripts\python.exe"
set "LOCAL_VENV=%ROOT_DIR%.venv\Scripts\python.exe"

cd /d "%ROOT_DIR%"

if exist "%LOCAL_VENV310%" (
  set "PYTHON_EXE=%LOCAL_VENV310%"
) else if exist "%LOCAL_VENV%" (
  set "PYTHON_EXE=%LOCAL_VENV%"
) else (
  set "PYTHON_EXE=python"
)

echo Starting Translate Manga CLI...
"%PYTHON_EXE%" "%APP_ENTRY%" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo Translate Manga CLI stopped with exit code %EXIT_CODE%.
) else (
  echo Translate Manga CLI finished.
)
exit /b %EXIT_CODE%
