param([switch]$SkipBuild, [int]$Port = 8000, [string]$PythonPath = 'backend/.venv/Scripts/python.exe')
$ErrorActionPreference = 'Stop'
$terminalRoot = $PSScriptRoot
$terminalPython = if ([System.IO.Path]::IsPathRooted($PythonPath)) { $PythonPath } else { Join-Path $terminalRoot $PythonPath }
if (-not (Test-Path -LiteralPath $terminalPython)) {
    throw 'Backend virtual environment missing. Follow the fresh-install steps in README.md.'
}
if (-not $SkipBuild) {
    Push-Location (Join-Path $terminalRoot 'frontend')
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
}
if (-not (Test-Path -LiteralPath (Join-Path $terminalRoot 'frontend\out\index.html'))) {
    throw 'Frontend export missing. Run without -SkipBuild first.'
}
Write-Host "Open http://127.0.0.1:$Port -- frontend and backend share this address."
Push-Location (Join-Path $terminalRoot 'backend')
try { & $terminalPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1 }
finally { Pop-Location }
