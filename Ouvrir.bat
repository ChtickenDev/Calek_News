@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ==========================================
REM  CALEK News - Lance Flask + ouvre navigateur
REM  Adaptatif au reseau (IP locale auto)
REM ==========================================

cd /d "%~dp0"

REM ----- Reglages -----
set "PORT=5000"
set "VENV_DIR=%CD%\.venv"
set "PYEXE=%VENV_DIR%\Scripts\python.exe"
set "REQFILE=%CD%\requirements.txt"
set "LOGDIR=%CD%\logs"
set "LOGFILE=%LOGDIR%\server.log"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [INFO] Dossier: "%CD%"
echo [INFO] Port: %PORT%

REM ====== Creer venv si necessaire ======
if not exist "%PYEXE%" (
  echo [SETUP] Creation de l'environnement virtuel .venv...
  py -3.13 -m venv "%VENV_DIR%"
)

if not exist "%PYEXE%" (
  echo [ERROR] Python du venv introuvable: "%PYEXE%"
  echo         -> Verifie que Python est installe et/ou supprime .venv puis relance.
  pause
  exit /b 1
)

REM ====== Installer dependances ======
echo [SETUP] Installation/maj des dependances...
"%PYEXE%" -m pip install --upgrade pip
if exist "%REQFILE%" (
  "%PYEXE%" -m pip install -r "%REQFILE%"
) else (
  echo [WARN] requirements.txt introuvable, on continue...
)

REM ====== Recuperer IP locale (reseau courant) ======
set "HOST_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command ^
  "$ip = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1).IPv4Address.IPAddress; if(-not $ip){$ip='127.0.0.1'}; Write-Output $ip"`) do (
  set "HOST_IP=%%I"
)

if "%HOST_IP%"=="" set "HOST_IP=127.0.0.1"

echo [INFO] IP locale detectee: %HOST_IP%

REM ====== Lancer Flask en ecoutant sur toutes les interfaces ======
echo [RUN] Demarrage du serveur...
REM Important: host=0.0.0.0 => accessible depuis autres appareils du meme Wi-Fi (si firewall OK)
start "CALEK News (server)" cmd /k ""%PYEXE%" "%CD%\app.py" --host 0.0.0.0 --port %PORT% 1^> "%LOGFILE%" 2^>^&1"

REM ====== Attendre que ca reponde puis ouvrir le navigateur ======
echo [WAIT] Attente de http://%HOST_IP%:%PORT% ...
powershell -NoProfile -Command ^
  "while (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port %PORT% -InformationLevel Quiet)) { Start-Sleep -Seconds 1 } ; Start-Process ('http://%HOST_IP%:%PORT%')"

echo [OK] Navigateur ouvert. Logs: "%LOGFILE%"
exit /b 0
