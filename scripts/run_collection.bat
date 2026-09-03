@echo off
REM Wrapper for Windows Task Scheduler — sets working directory so relative
REM paths (.env, data/raw) resolve correctly regardless of the scheduler's
REM default start-in directory. Registered by scripts/register_task.ps1.
cd /d "%~dp0.."
".venv\Scripts\python.exe" "scripts\run_collection.py" >> "logs\collection.log" 2>&1
