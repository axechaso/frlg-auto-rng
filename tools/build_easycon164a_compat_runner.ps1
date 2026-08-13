$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root ".build\easycon164a"
$output = Join-Path $root "runtime_backend\easycon164a-cli-gui-rounding-selfcontained"
$patch = Join-Path $PSScriptRoot "patches\easycon164a-cli-gui-rounding.patch"
$commit = "9c86137c7e63bff842175470895727a5fa9bab52"

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

dotnet publish $project -c Release --no-restore -r win-x64 `
    -p:DefaultTargetFramework=net9.0 `
    -p:LtsTargetFramework=net9.0 `
    -p:PublishSingleFile=true `
    -p:SelfContained=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:DebugType=None `
    -p:DebugSymbols=false `
    -o $output
if ($LASTEXITCODE -ne 0) { throw "Compatibility runner build failed" }

$runner = Join-Path $output "EasyCon2.CLI.exe"
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $runner).Hash.ToLowerInvariant()
$length = (Get-Item -LiteralPath $runner).Length
$manifest = [ordered]@{
    source_repository = "https://github.com/EasyConNS/EasyCon.git"
    source_commit = $commit
    source_version = "1.6.4-a"
    patch_id = "cli-image-label-ceiling-v1"
    description = "Make ezcon run round ImgLabel confidence with Math.Ceiling, matching the EasyCon 1.6.4-a GUI."
    build_target = "net9.0/win-x64 self-contained single-file"
    filename = "EasyCon2.CLI.exe"
    bytes = $length
    sha256 = $hash
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output "build-manifest.json") -Encoding utf8

Write-Host "Built: $runner"
Write-Host "SHA256: $hash"
