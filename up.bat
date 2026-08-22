@echo off
cd /d %~dp0
git init
git add .
git ls-files
git commit -m "Auto commit %date% %time%"
git push -f origin main
pause