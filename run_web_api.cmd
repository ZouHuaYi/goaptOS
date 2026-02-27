@echo off
cd /d "%~dp0"
python -m gtos.web.chat_server --host 127.0.0.1 --port 8000
