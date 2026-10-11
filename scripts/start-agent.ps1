$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$apiRoot = Join-Path $repoRoot "apps/api"
$webRoot = Join-Path $repoRoot "apps/web"
$venvRoot = Join-Path $apiRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts/python.exe"

if (-not (Test-Path $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv $venvRoot
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $venvRoot
    } else {
        throw "需要先安装 Python 3.12"
    }
    if ($LASTEXITCODE -ne 0) { throw "创建 Python 虚拟环境失败" }
}

& $venvPython -c "import sys; assert sys.version_info[:2] == (3, 12)"
if ($LASTEXITCODE -ne 0) { throw "需要 Python 3.12 虚拟环境" }

& $venvPython -c "import fastapi, keyring"
if ($LASTEXITCODE -ne 0) {
    & $venvPython -m pip install -e $apiRoot
    if ($LASTEXITCODE -ne 0) { throw "安装后端依赖失败" }
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "需要先安装 Node.js 20+"
}
if (-not (Test-Path (Join-Path $webRoot "node_modules"))) {
    & npm.cmd --prefix $webRoot install
    if ($LASTEXITCODE -ne 0) { throw "安装前端依赖失败" }
}

$processes = @()
try {
    $processes += Start-Process -FilePath $venvPython -ArgumentList @(
        "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8002"
    ) -WorkingDirectory $apiRoot -PassThru -NoNewWindow
    $processes += Start-Process -FilePath $venvPython -ArgumentList @(
        "-m", "app.v0.worker"
    ) -WorkingDirectory $apiRoot -PassThru -NoNewWindow
    $processes += Start-Process -FilePath "npm.cmd" -ArgumentList @(
        "run", "dev", "--", "--host", "127.0.0.1", "--port", "5176", "--strictPort"
    ) -WorkingDirectory $webRoot -PassThru -NoNewWindow

    Write-Host "前端: http://127.0.0.1:5176"
    Write-Host "API:  http://127.0.0.1:8002/docs"
    Write-Host "Worker: 本机独立进程（无端口）"
    Write-Host "按 Ctrl+C 停止"
    while ($true) {
        Start-Sleep -Seconds 1
        foreach ($process in $processes) {
            if ($process.HasExited) { throw "一个本机服务已退出（PID $($process.Id)）" }
        }
    }
} finally {
    foreach ($process in $processes) {
        if (-not $process.HasExited) {
            & taskkill.exe /PID $process.Id /T /F *> $null
        }
    }
}
