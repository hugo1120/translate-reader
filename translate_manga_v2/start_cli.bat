@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "APP_ENTRY=%ROOT_DIR%batch_translate.py"
set "MENU_MODULE=translate_manga.cli.menu"
set "LOCAL_VENV310=%ROOT_DIR%.venv310\Scripts\python.exe"
set "LOCAL_VENV=%ROOT_DIR%.venv\Scripts\python.exe"
set "PYTHONPATH=%ROOT_DIR%src;%PYTHONPATH%"

cd /d "%ROOT_DIR%"

if exist "%LOCAL_VENV310%" (
  set "PYTHON_EXE=%LOCAL_VENV310%"
) else if exist "%LOCAL_VENV%" (
  set "PYTHON_EXE=%LOCAL_VENV%"
) else (
  set "PYTHON_EXE=python"
)

echo Starting Translate Manga V2...
if "%~1"=="" (
  "%PYTHON_EXE%" -m %MENU_MODULE%
) else (
  "%PYTHON_EXE%" "%APP_ENTRY%" %*
)
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo Translate Manga V2 stopped with exit code %EXIT_CODE%.
  if "%EXIT_CODE%"=="2" if not "%~1"=="" call :print_usage_hint
) else (
  echo Translate Manga V2 finished.
)
exit /b %EXIT_CODE%

:print_usage_hint
echo.
echo Example:
echo   start_cli.bat --input "D:/path/to/input" --output "D:/path/to/output" --style-id 2
echo   start_cli.bat "D:/path/to/input" "D:/path/to/output" --style-id 3
echo   start_cli.bat --input "D:/path/to/input" --output "D:/path/to/output" --retry-review-pages
echo.
echo Style 1 = horizontal JP
echo Style 2 = vertical JP
echo Style 3 = horizontal EN
goto :eof
