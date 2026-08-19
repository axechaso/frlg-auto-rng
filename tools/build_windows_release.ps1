param(
    [string]$Python = "",
    [string]$EasyConPublish = "",
    [string]$OutputName = "FRLG-Auto-RNG-绿色版"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Python) {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "找不到 Python 构建环境：$Python"
}

if (-not $EasyConPublish) {
    $candidate = Get-ChildItem -LiteralPath (Join-Path $Root "dist") -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "easycon\publish" } |
        Where-Object { Test-Path -LiteralPath (Join-Path $_ "ezcon.exe") } |
        Select-Object -First 1
    if ($candidate) { $EasyConPublish = $candidate }
}
if (-not $EasyConPublish -or -not (Test-Path -LiteralPath (Join-Path $EasyConPublish "ezcon.exe"))) {
    throw "找不到 EasyCon publish 目录。请用 -EasyConPublish 指定包含 ezcon.exe 的目录。"
}

& $Python -m pip install --disable-pip-version-check "pyinstaller==6.15.0"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 安装失败" }

$BuildRoot = Join-Path $Root ".build\windows-release"
$PyInstallerWork = Join-Path $BuildRoot "pyinstaller"
$PyInstallerDist = Join-Path $BuildRoot "dist"
$ReleaseRoot = Join-Path $BuildRoot $OutputName
Remove-Item -Force -Recurse -LiteralPath $BuildRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $BuildRoot | Out-Null

$args = @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
    "--name", "FRLG-Auto-RNG", "--distpath", $PyInstallerDist,
    "--workpath", $PyInstallerWork, "--specpath", $BuildRoot,
    "--hidden-import", "run_sid_reverse_capture",
    "--hidden-import", "run_tid_starter_flow",
    "--hidden-import", "run_easycon_logged",
    "--hidden-import", "calibration_bind",
    "--hidden-import", "cv2",
    "--add-data", "$(Join-Path $Root 'assets');assets",
    "--add-data", "$(Join-Path $Root 'rng\resources');rng\resources",
    "--add-data", "$(Join-Path $Root 'local_assets');local_assets",
    "--add-data", "$(Join-Path $Root 'runtime_backend');runtime_backend",
    "--add-data", "$(Join-Path $Root 'default.yaml');.",
    "--add-binary", "$(Join-Path $Root 'rng\src\pybind\calibration_bind.cp312-win_amd64.pyd');rng\src\pybind",
    (Join-Path $Root 'package_entry.py')
)
Push-Location $Root
try {
    & $Python @args
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Path (Join-Path $PyInstallerDist "FRLG-Auto-RNG\easycon\publish") -Force | Out-Null
$InternalRoot = Join-Path $PyInstallerDist "FRLG-Auto-RNG\_internal"
New-Item -ItemType Directory -Path (Join-Path $InternalRoot "easycon\publish") -Force | Out-Null
Copy-Item -Force -Recurse -Path (Join-Path $EasyConPublish "*") -Destination (Join-Path $InternalRoot "easycon\publish")

New-Item -ItemType Directory -Path $ReleaseRoot | Out-Null
Copy-Item -Force -Recurse -Path (Join-Path $PyInstallerDist "FRLG-Auto-RNG\*") -Destination $ReleaseRoot
Set-Content -LiteralPath (Join-Path $ReleaseRoot "启动-FRLG-Auto-RNG.bat") -Encoding UTF8 -Value @('@echo off','chcp 65001 >nul','cd /d "%~dp0"','start "FRLG Auto RNG" "%~dp0FRLG-Auto-RNG.exe"')
Set-Content -LiteralPath (Join-Path $ReleaseRoot "使用说明.txt") -Encoding UTF8 -Value @(
    "FRLG Auto RNG 绿色版",
    "",
    "双击 FRLG-Auto-RNG.exe，或双击 启动-FRLG-Auto-RNG.bat。",
    "本包不需要安装 Python、pygame 或其他 Python 依赖。",
    "首次运行生成的配置、日志和 ECS 工程保存在 %LOCALAPPDATA%\FRLG-Auto-RNG。",
    "使用前仍需连接 EasyCon 兼容单片机和采集卡，并在界面检测设备。"
)

$ZipPath = Join-Path $BuildRoot "$OutputName.zip"
Compress-Archive -Force -Path (Join-Path $ReleaseRoot "*") -DestinationPath $ZipPath
Write-Host "发布目录：$ReleaseRoot"
Write-Host "发布压缩包：$ZipPath"
