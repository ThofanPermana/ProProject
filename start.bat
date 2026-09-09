@echo off
echo ── Membersihkan proses lama ──────────────────────────────────────────────

:: Matikan Telegram bot / webui (python dari venv Hermes) yang masih jalan
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7860 "') do (
    taskkill /PID %%a /F >nul 2>&1
)
:: Matikan Ollama jika sudah running (agar tidak error "port in use")
taskkill /IM ollama.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo ── Menjalankan Ollama ───────────────────────────────────────────────────
start "" /B "C:\Users\Thofa\AppData\Local\Programs\Ollama\ollama.exe" serve
timeout /t 5 /nobreak >nul

echo ── Menjalankan Hermes WebUI di http://localhost:7860 ────────────────────
start "" /B "d:\Hermes\.venv\Scripts\python.exe" d:\Hermes\webui\app.py
timeout /t 3 /nobreak >nul
start "" http://localhost:7860

echo ── Menjalankan Hermes Telegram agent ────────────────────────────────────
cd /d d:\Hermes
"d:\Hermes\.venv\Scripts\python.exe" main.py
