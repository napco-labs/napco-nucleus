@echo off
REM AI Agent launcher. Usage:
REM   run_agent.bat                                 (full test cycle + email)
REM   run_agent.bat "review integration tests"      (custom prompt)

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

python main.py %*
