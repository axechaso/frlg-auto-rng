$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root ".build\easycon164a"
$output = Join-Path $root "runtime_backend\easycon164a-cli-gui-rounding-selfcontained"
$buildRoot = [IO.Path]::GetFullPath((Join-Path $root ".build"))
$staging = [IO.Path]::GetFullPath((Join-Path $buildRoot "publish-easycon164a-compat"))
$patch = Join-Path $PSScriptRoot "patches\easycon164a-cli-gui-rounding.patch"
$commit = "9c86137c7e63bff842175470895727a5fa9bab52"
$runnerFilename = "EasyCon2.CLI-ocr-v4.exe"

if (-not (Test-Path -LiteralPath (Join-Path $source ".git"))) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $source) | Out-Null
    git clone https://github.com/EasyConNS/EasyCon.git $source
    if ($LASTEXITCODE -ne 0) { throw "EasyCon source clone failed" }
    git -C $source checkout --detach $commit
    if ($LASTEXITCODE -ne 0) { throw "EasyCon 1.6.4-a commit checkout failed" }
}

$actualCommit = (git -c "safe.directory=$source" -C $source rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Unable to inspect the EasyCon build source" }
if ($actualCommit -ne $commit) {
    throw "Existing build source is not the pinned EasyCon 1.6.4-a commit: $actualCommit"
}

git -c "safe.directory=$source" -C $source apply --reverse --check $patch 2>$null
if ($LASTEXITCODE -ne 0) {
    git -c "safe.directory=$source" -C $source apply --check $patch
    if ($LASTEXITCODE -ne 0) { throw "EasyCon compatibility patch does not apply cleanly" }
    git -c "safe.directory=$source" -C $source apply $patch
    if ($LASTEXITCODE -ne 0) { throw "EasyCon compatibility patch failed" }
}

$project = Join-Path $source "src\EasyCon2.CLI\EasyCon2.CLI.csproj"
dotnet restore $project -r win-x64 -p:DefaultTargetFramework=net9.0 -p:LtsTargetFramework=net9.0
if ($LASTEXITCODE -ne 0) { throw "NuGet restore failed" }

if (Test-Path -LiteralPath $staging) {
    $expectedPrefix = $buildRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $staging.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clear a staging directory outside .build: $staging"
    }
    Remove-Item -LiteralPath $staging -Recurse -Force
}

dotnet publish $project -c Release --no-restore -r win-x64 -t:Rebuild `
    -p:DefaultTargetFramework=net9.0 `
    -p:LtsTargetFramework=net9.0 `
    -p:PublishSingleFile=false `
    -p:SelfContained=true `
    -p:DebugType=None `
    -p:DebugSymbols=false `
    -o $staging
if ($LASTEXITCODE -ne 0) { throw "Compatibility runner build failed" }

$stagedRunner = Join-Path $staging "EasyCon2.CLI.exe"
if (-not (Test-Path -LiteralPath $stagedRunner)) {
    throw "Compatibility runner publish did not produce EasyCon2.CLI.exe"
}
$stagedVersion = (& $stagedRunner --version | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or $stagedVersion -ne "1.6.4-a+$commit") {
    throw "Staged compatibility runner failed its version check: $stagedVersion"
}

New-Item -ItemType Directory -Force -Path $output | Out-Null
$runner = Join-Path $output $runnerFilename
Get-ChildItem -LiteralPath $staging -Force | Where-Object { $_.Name -ne "EasyCon2.CLI.exe" } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $output -Recurse -Force
}
Copy-Item -LiteralPath $stagedRunner -Destination $runner -Force
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $runner).Hash.ToLowerInvariant()
$length = (Get-Item -LiteralPath $runner).Length
$manifest = [ordered]@{
    source_repository = "https://github.com/EasyConNS/EasyCon.git"
    source_commit = $commit
    source_version = "1.6.4-a"
    patch_id = "cli-latest-frame-ceiling-ocr-onedir-v4"
    description = "Continuously capture the newest DSHOW frame, share it with local OCR, log its dimensions, and use the EasyCon 1.6.4-a GUI's Math.Ceiling confidence rounding."
    build_target = "net9.0/win-x64 self-contained onedir"
    filename = $runnerFilename
    bytes = $length
    sha256 = $hash
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output "build-manifest.json") -Encoding utf8

Write-Host "Built: $runner"
Write-Host "SHA256: $hash"
