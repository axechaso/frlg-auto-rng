param(
    [string]$Python = "",
    [string]$EasyConPublish = "",
    [string]$OutputName = "",
    [string]$BuildTag = "",
    [string]$LocalAssets = "",
    [string]$NotesFile = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Python) {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "找不到 Python 构建环境：$Python"
}
$AppVersion = (& $Python -c "import sys; sys.path.insert(0, r'$Root'); from app_version import APP_VERSION; print(APP_VERSION)" | Select-Object -Last 1).Trim()
if (-not $AppVersion -or $AppVersion -notmatch '^[0-9]+\.[0-9]+(?:\.[0-9]+){0,2}$') {
    throw "无法读取 app_version.py 中的应用版本"
}
if (-not $OutputName) {
    $OutputName = "FRLG-Auto-RNG-$AppVersion-windows-x64"
}
if ($OutputName -ne "FRLG-Auto-RNG-$AppVersion-windows-x64") {
    throw "$AppVersion 发布包必须使用标准名称 FRLG-Auto-RNG-$AppVersion-windows-x64"
}
if ($BuildTag -and $BuildTag -notmatch '^[a-zA-Z0-9-]+$') {
    throw "BuildTag 只能包含字母、数字和短横线"
}
$BuildSuffix = if ($BuildTag) { "-$BuildTag" } else { "" }
$BuildRoot = Join-Path $Root ".build\windows-release$BuildSuffix"
if (Test-Path -LiteralPath $BuildRoot) {
    throw "构建目录已存在，已保留旧包。请使用新的 -BuildTag：$BuildRoot"
}
if (-not $LocalAssets) { $LocalAssets = Join-Path $Root "local_assets" }
$LocalAssets = (Resolve-Path -LiteralPath $LocalAssets).Path
if (-not $NotesFile) { $NotesFile = Join-Path $Root "docs\releases\v$AppVersion.md" }
$NotesFile = (Resolve-Path -LiteralPath $NotesFile).Path
if (-not (Test-Path -LiteralPath $NotesFile -PathType Leaf)) {
    throw "找不到发布说明：$NotesFile"
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

& $Python -m pip install --disable-pip-version-check "pyinstaller==6.15.0" "PySide6==6.11.2" "truststore==0.10.4"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller / PySide6 / truststore 安装失败" }

$PyInstallerWork = Join-Path $BuildRoot "pyinstaller"
$PyInstallerDist = Join-Path $BuildRoot "dist"
$UpdaterWork = Join-Path $BuildRoot "updater-pyinstaller"
$UpdaterDist = Join-Path $BuildRoot "updater-dist"
$ReleaseRoot = Join-Path $BuildRoot $OutputName
New-Item -ItemType Directory -Path $BuildRoot | Out-Null

$args = @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
    "--name", "FRLG-Auto-RNG", "--distpath", $PyInstallerDist,
    "--workpath", $PyInstallerWork, "--specpath", $BuildRoot,
    "--hidden-import", "run_sid_reverse_capture",
    "--hidden-import", "run_sid_traversal",
    "--hidden-import", "run_tid_starter_flow",
    "--hidden-import", "run_easycon_logged",
    "--hidden-import", "run_pyside6_gui",
    "--hidden-import", "calibration_bind",
    "--hidden-import", "cv2",
    # PyInstaller's PySide6 hook follows the Qt modules imported by the app and
    # collects their required plugins.  Collecting the whole PySide6 wheel also
    # ships unused QML/tooling plugins, adds hundreds of MiB, and can make Qt
    # fail during process shutdown because unrelated plugin DLLs are loaded.
    "--collect-submodules", "truststore",
    "--exclude-module", "tkinter",
    "--exclude-module", "tkinterdnd2",
    "--add-data", "$(Join-Path $Root 'assets');assets",
    "--add-data", "$(Join-Path $Root 'rng\resources');rng\resources",
    "--add-data", "$LocalAssets;local_assets",
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

# Qt 6.11 on Windows links Qt6Core against the unversioned Windows ICU API.
# A build host can have a third-party icuuc.dll (for example Poppler's ICU 78)
# earlier on PATH; PyInstaller may then collect that incompatible DLL into
# _internal.  It exports only version-suffixed symbols and makes QtCore fail
# with ERROR_PROC_NOT_FOUND.  PySide6's wheel deliberately does not ship this
# DLL, so remove only foreign ICU files collected at the _internal root and
# let Windows resolve its own System32 ICU implementation.
$MainInternalRoot = Join-Path $PyInstallerDist "FRLG-Auto-RNG\_internal"
$SystemIcu = Join-Path $env:WINDIR "System32\icuuc.dll"
if (-not (Test-Path -LiteralPath $SystemIcu -PathType Leaf)) {
    throw "当前 Windows 缺少 PySide6 所需的系统 ICU：$SystemIcu"
}
$ForeignIcuPatterns = @("icuuc.dll", "icudt*.dll", "icuin*.dll")
foreach ($ForeignIcuPattern in $ForeignIcuPatterns) {
    Get-ChildItem -LiteralPath $MainInternalRoot -File -Filter $ForeignIcuPattern -ErrorAction SilentlyContinue |
        ForEach-Object {
            $ForeignIcu = $_
            Write-Host "移除构建环境误收的 ICU：$($ForeignIcu.Name)"
            Remove-Item -Force -LiteralPath $ForeignIcu.FullName
        }
}

$updaterArgs = @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "FRLG-Auto-RNG-Updater", "--distpath", $UpdaterDist,
    "--workpath", $UpdaterWork, "--specpath", $BuildRoot,
    "--collect-submodules", "truststore",
    (Join-Path $Root 'updater_entry.py')
)
Push-Location $Root
try {
    & $Python @updaterArgs
    if ($LASTEXITCODE -ne 0) { throw "独立更新器打包失败" }
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Path (Join-Path $PyInstallerDist "FRLG-Auto-RNG\easycon\publish") -Force | Out-Null
$InternalRoot = Join-Path $PyInstallerDist "FRLG-Auto-RNG\_internal"
New-Item -ItemType Directory -Path (Join-Path $InternalRoot "easycon\publish") -Force | Out-Null
Copy-Item -Force -Recurse -Path (Join-Path $EasyConPublish "*") -Destination (Join-Path $InternalRoot "easycon\publish")

New-Item -ItemType Directory -Path $ReleaseRoot | Out-Null
Copy-Item -Force -Recurse -Path (Join-Path $PyInstallerDist "FRLG-Auto-RNG\*") -Destination $ReleaseRoot
Copy-Item -Force -LiteralPath (Join-Path $UpdaterDist "FRLG-Auto-RNG-Updater.exe") -Destination (Join-Path $ReleaseRoot "FRLG-Auto-RNG-Updater.exe")
Set-Content -LiteralPath (Join-Path $ReleaseRoot "启动-FRLG-Auto-RNG.bat") -Encoding UTF8 -Value @('@echo off','chcp 65001 >nul','cd /d "%~dp0"','start "FRLG Auto RNG" "%~dp0FRLG-Auto-RNG.exe"')
Set-Content -LiteralPath (Join-Path $ReleaseRoot "使用说明.txt") -Encoding UTF8 -Value @(
    "FRLG Auto RNG 绿色版",
    "",
    "双击 FRLG-Auto-RNG.exe，或双击 启动-FRLG-Auto-RNG.bat。",
    "本包不需要安装 Python、pygame 或其他 Python 依赖。",
    "首次运行生成的配置、日志和 ECS 工程保存在 %LOCALAPPDATA%\FRLG-Auto-RNG。",
    "使用前仍需连接 EasyCon 兼容单片机和采集卡，并在界面检测设备。"
)

# The generator has a local_assets fallback for Windows builds where
# PyInstaller mangles non-ASCII names under assets.  Keep the fallback a hard
# release invariant so a package can never ship without the exact EasyCon
# label names required by the generated ECS project.
$BundledLabelDir = Join-Path $ReleaseRoot "_internal\local_assets\easycon118\ImgLabel"
foreach ($RequiredLabel in @("闪公图标.IL", "冲浪.IL")) {
    $RequiredLabelPath = Join-Path $BundledLabelDir $RequiredLabel
    if (-not (Test-Path -LiteralPath $RequiredLabelPath -PathType Leaf)) {
        throw "发布包缺少 EasyCon 扩展标签：$RequiredLabelPath"
    }
}

$frozenMain = Join-Path $ReleaseRoot "FRLG-Auto-RNG.exe"
Push-Location $Root
try {
    & $Python -m tools.verify_frozen_workers --exe $frozenMain
    if ($LASTEXITCODE -ne 0) { throw "冻结后台工作进程检查失败，停止打包" }
} finally {
    Pop-Location
}

$ZipPath = Join-Path $BuildRoot "$OutputName.zip"
# The release folder is self-contained. Remove PyInstaller's temporary copy
# before compression so the archive does not require another full package's
# worth of free disk space.
foreach ($IntermediatePath in @($PyInstallerDist, $PyInstallerWork, $UpdaterDist, $UpdaterWork, (Join-Path $BuildRoot "FRLG-Auto-RNG.spec"), (Join-Path $BuildRoot "FRLG-Auto-RNG-Updater.spec"))) {
    if (Test-Path -LiteralPath $IntermediatePath) {
        Remove-Item -Force -Recurse -LiteralPath $IntermediatePath
    }
}
Compress-Archive -Force -Path (Join-Path $ReleaseRoot "*") -DestinationPath $ZipPath
Push-Location $Root
try {
    & $Python -m tools.create_update_manifest --package $ZipPath --unpacked-root $ReleaseRoot --notes-file $NotesFile
    if ($LASTEXITCODE -ne 0) { throw "更新清单生成失败" }
} finally {
    Pop-Location
}

# PyInstaller's windowed bootloader can lose non-ASCII command-line paths on
# some Windows hosts.  Keep the probe in a temporary path and use a separate
# process so its real exit code is available even without a console.
$probeTempRoot = [IO.Path]::GetTempPath()
$versionProbe = Join-Path $probeTempRoot ("frlg-auto-rng-version-" + [guid]::NewGuid().ToString("N") + ".json")
$probeProcess = Start-Process -FilePath $frozenMain -ArgumentList @("--version-json-file", $versionProbe) -Wait -PassThru -WindowStyle Hidden
if ($probeProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $versionProbe -PathType Leaf)) {
    Remove-Item -Force -LiteralPath $versionProbe -ErrorAction SilentlyContinue
    throw "冻结主程序版本探针失败（退出码 $($probeProcess.ExitCode)）"
}
$probe = Get-Content -LiteralPath $versionProbe -Raw | ConvertFrom-Json
if ($probe.version -ne $AppVersion -or $probe.repository -ne "axechaso/frlg-auto-rng") {
    throw "冻结主程序内嵌版本与构建版本不一致"
}
Remove-Item -Force -LiteralPath $versionProbe

$smokeRoot = Join-Path $probeTempRoot ("frlg-auto-rng-pyside-smoke-" + [guid]::NewGuid().ToString("N"))
$smokeData = Join-Path $smokeRoot "user"
$smokePng = Join-Path $smokeRoot "pyside6.png"
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
try {
    $smokeProcess = Start-Process -FilePath $frozenMain -ArgumentList @(
        "--screenshot", $smokePng,
        "--data-dir", $smokeData,
        "--no-device-check"
    ) -Wait -PassThru -WindowStyle Hidden
    if ($smokeProcess.ExitCode -ne 0 -or
        -not (Test-Path -LiteralPath $smokePng -PathType Leaf) -or
        (Get-Item -LiteralPath $smokePng).Length -le 0) {
        throw "冻结 PySide6 主界面冒烟失败（退出码 $($smokeProcess.ExitCode)）"
    }
} finally {
    Remove-Item -Force -Recurse -LiteralPath $smokeRoot -ErrorAction SilentlyContinue
}
Write-Host "发布目录：$ReleaseRoot"
Write-Host "发布压缩包：$ZipPath"
Write-Host "更新清单：$(Join-Path $BuildRoot 'update-manifest.json')"
Write-Host "SHA-256：$(Join-Path $BuildRoot "$OutputName.zip.sha256")"
