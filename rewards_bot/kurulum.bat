@echo off
rem Rewards bot kurulumu: Python, paketler, giris, gunluk otomatik gorev ve ilk calistirma.
chcp 65001 >nul
cd /d "%~dp0.."

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if defined PY (
  %PY% --version >nul 2>nul || set "PY="
)

if not defined PY (
  echo Python bulunamadi, winget ile kuruluyor...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo Python kurulamadi. https://www.python.org/downloads/ adresinden Python 3 kurun
  echo ^(kurulumda "Add python.exe to PATH" kutusunu isaretleyin^) ve bu dosyayi tekrar calistirin.
  pause
  exit /b 1
)

if not exist ".venv-rewards\Scripts\python.exe" (
  echo Python ortami olusturuluyor...
  %PY% -m venv .venv-rewards || goto :error
)
set "VPY=.venv-rewards\Scripts\python.exe"

echo Gerekli paketler kuruluyor...
%VPY% -m pip install --quiet --upgrade pip || goto :error
%VPY% -m pip install --quiet -r rewards_bot\requirements.txt || goto :error

echo.
echo Simdi bir tarayici penceresi acilacak: Microsoft hesabinizla giris yapin.
%VPY% -m rewards_bot login || goto :error

echo.
%VPY% -m rewards_bot install-task || goto :error

echo.
echo Bot simdi arka planda calismaya basliyor; pencere acmaz, bilgisayarinizi kullanmaya devam edebilirsiniz.
schtasks /Run /TN RewardsBot >nul 2>nul || start "" /b .venv-rewards\Scripts\pythonw.exe -m rewards_bot run --once-per-day
echo Ilerleme: logs\rewards_bot.log   Durum: %VPY% -m rewards_bot status
echo Bundan sonra her gun kendiliginden calisir. Bu pencereyi kapatabilirsiniz.
pause
exit /b 0

:error
echo.
echo Bir hata olustu; yukaridaki mesaja bakin.
pause
exit /b 1
