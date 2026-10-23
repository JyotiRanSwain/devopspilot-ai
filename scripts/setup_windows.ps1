# One-time setup on Windows 11 (PowerShell, from the project folder)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Write-Host "Done. Start the dashboard with: python -m app"
