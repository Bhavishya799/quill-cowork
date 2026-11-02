@echo off
cd /d "%~dp0"
call backend\venv\Scripts\activate.bat
cd backend

:: Start the quick assistant in the background
start /B python quick_assistant.py

:: Open the browser and start the main server
start http://localhost:8000
python main.py
pause
