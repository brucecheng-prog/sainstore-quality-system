@echo off
setlocal
cd /d %~dp0
powershell -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1"
pause
