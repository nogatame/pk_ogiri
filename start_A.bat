@echo off
title PK_OGIRI - Room A (Port 5000)
echo Starting Python Flask Server on Port 5000...
start cmd /k "python pk_ogiri.py"
echo Starting Localtunnel for Room A (https://pk-ogiri-a.localtunnel.me)...
npx localtunnel --port 5000 --subdomain pk-ogiri-a
pause
