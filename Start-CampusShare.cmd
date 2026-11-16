@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    "%LocalAppData%\Programs\Python\Python312\python.exe" -m venv .venv
) else (
    py -3.12 -m venv .venv
)
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Open http://127.0.0.1:8000 in your browser when startup completes.
".venv\Scripts\python.exe" demo.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo CampusShare could not start. Check the message above.
pause
exit /b 1
