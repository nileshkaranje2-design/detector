#Requires -Version 5.1
# Launch the Multiplier Detection GUI app.
$ErrorActionPreference = 'Stop'

Set-Location -LiteralPath $PSScriptRoot

$envFile = Join-Path $PSScriptRoot '.env'
$envExample = Join-Path $PSScriptRoot '.env.example'

if (-not (Test-Path -LiteralPath $envFile)) {
    if (Test-Path -LiteralPath $envExample) {
        Write-Host 'No .env found. Creating one from .env.example...'
        Copy-Item -LiteralPath $envExample -Destination $envFile
        Write-Host "Edit .env to set TESSERACT_CMD and OPENAI_API_KEY before running detection."
    } else {
        Write-Warning 'No .env and no .env.example found; the app will fall back to its defaults.'
    }
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Virtual environment not found. Creating one and installing dependencies...'

    $bootstrap = (Get-Command py -ErrorAction SilentlyContinue)
    if ($bootstrap) {
        & py -3 -m venv .venv
    } else {
        $bootstrap = (Get-Command python -ErrorAction SilentlyContinue)
        if (-not $bootstrap) {
            Write-Error 'Python was not found on PATH. Install Python 3 from python.org and try again.'
        }
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create virtual environment (exit $LASTEXITCODE)." }

    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to install dependencies (exit $LASTEXITCODE)." }
}

& $python app.py @args
exit $LASTEXITCODE
