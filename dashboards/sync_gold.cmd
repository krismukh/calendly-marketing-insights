@echo off
REM Download the Gold CSV exports from ADLS Gen2 into dashboards\data\export\
REM Requires Azure CLI signed in: az login --tenant <tenant id>
setlocal
set ACCOUNT=stcalendlykcm
set TARGET=%~dp0data
if exist "%TARGET%\export" rmdir /s /q "%TARGET%\export"
if not exist "%TARGET%" mkdir "%TARGET%"
echo Downloading gold/export from %ACCOUNT% ...
az storage fs directory download -f gold -s export -d "%TARGET%" --recursive --account-name %ACCOUNT% --auth-mode login --only-show-errors
if errorlevel 1 (
  echo Download failed. Run: az login
  exit /b 1
)
echo Done. Files are under %TARGET%\export\
endlocal
