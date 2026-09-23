@echo off
REM Run from the repo root on Windows, inside the venv:
REM   .venv\Scripts\activate
REM   packaging\build-windows.bat
setlocal
cd /d "%~dp0.."

pushd frontend
call yarn build
popd

.venv\Scripts\pyinstaller packaging\su1ra.spec --noconfirm --distpath packaging\dist --workpath packaging\build
if errorlevel 1 exit /b 1

"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" packaging\su1ra.iss
if errorlevel 1 exit /b 1

echo Installer: packaging\output\Su1ra-setup-x64.exe
