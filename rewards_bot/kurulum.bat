@echo off
rem Rewards bot kurulumu: Python ortamı, giriş ve günlük otomatik görev.
chcp 65001 >nul
cd /d "%~dp0.."

set "PY=py -3"
where py >nul 2>nul || set "PY=python"
%PY% --version >nul 2>nul || (
  echo Python bulunamadi. https://www.python.org/downloads/ adresinden Python 3 kurun
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
echo Kurulum tamam. Bot her gun arka planda kendiliginden calisacak.
echo Hemen denemek icin: %VPY% -m rewards_bot run
pause
exit /b 0

:error
echo.
echo Bir hata olustu; yukaridaki mesaja bakin.
pause
exit /b 1
