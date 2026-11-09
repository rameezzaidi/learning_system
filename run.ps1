# EduPulse launcher: asks for the key, sets everything up, starts the server.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if ((-not $env:GEMINI_API_KEY) -and -not (Test-Path ".env")) {
  $k = Read-Host "Gemini API key paste karein (Enter dabayein, khali chhorna ho to AI band rahega)"
  if ($k) { $env:GEMINI_API_KEY = $k.Trim().Trim('"') }
}
python -m pip install -r requirements.txt -q
python manage.py migrate -v 0
if (-not (Test-Path "db.sqlite3.seeded")) { python manage.py seed_demo; New-Item db.sqlite3.seeded -ItemType File | Out-Null }
Write-Host "`nOpen: http://127.0.0.1:8000   (admin/admin123, teacher1/demo123, student1/demo123, parent1/demo123)`n"
python manage.py runserver
