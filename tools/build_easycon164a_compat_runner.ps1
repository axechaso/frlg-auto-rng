$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root ".build\easycon164a-clean"
$output = Join-Path $root "runtime_backend\easycon164a-cli-gui-rounding-selfcontained"
$buildRoot = [IO.Path]::GetFullPath((Join-Path $root ".build"))
$patch = Join-Path $PSScriptRoot "patches\easycon164a-cli-gui-rounding-next.patch"
$commit = "9c86137c7e63bff842175470895727a5fa9bab52"
$sourceCommitMarker = Join-Path $source ".easycon-source-commit"
$assemblyName = "EasyCon2.CLI.PreviewV5"
$runnerFilename = "$assemblyName.exe"
$stagingName = "publish-easycon164a-compat-$assemblyName-$PID"
$staging = [IO.Path]::GetFullPath((Join-Path $buildRoot $stagingName))

function Copy-ChangedFile {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath
    )

    if (Test-Path -LiteralPath $DestinationPath) {
        $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SourcePath).Hash
        $destinationHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $DestinationPath).Hash
        if ($sourceHash -eq $destinationHash) {
            return
        }
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $DestinationPath) | Out-Null
    Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
}

if (-not (Test-Path -LiteralPath $source)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $source) | Out-Null
    git clone https://github.com/EasyConNS/EasyCon.git $source
    if ($LASTEXITCODE -ne 0) { throw "EasyCon source clone failed" }
    git -C $source checkout --detach $commit
    if ($LASTEXITCODE -ne 0) { throw "EasyCon 1.6.4-a commit checkout failed" }
}

if (Test-Path -LiteralPath $sourceCommitMarker) {
    $actualCommit = (Get-Content -LiteralPath $sourceCommitMarker -Raw).Trim()
} elseif (Test-Path -LiteralPath (Join-Path $source ".git")) {
    $actualCommit = (git -c "safe.directory=$source" -C $source rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect the EasyCon build source" }
} else {
    throw "Existing EasyCon source has neither Git metadata nor a pinned archive marker: $source"
}
if ($actualCommit -ne $commit) {
    throw "Existing build source is not the pinned EasyCon 1.6.4-a commit: $actualCommit"
}

$sourceGit = Join-Path $source ".git"
if (-not (Test-Path -LiteralPath $sourceGit)) {
    git -C $source init --quiet
    if ($LASTEXITCODE -ne 0) { throw "Unable to initialize the archived EasyCon source worktree" }
}

$binderSource = Join-Path $source "src\EasyCon.Script\Binding\Binder.cs"
$compilationSource = Join-Path $source "src\EasyCon.Script\Compilation.cs"
$evaluatorSource = Join-Path $source "src\EasyCon.Script\Evaluator.cs"
$cliProjectSource = Join-Path $source "src\EasyCon2.CLI\EasyCon2.CLI.csproj"
$mockGamePadSource = Join-Path $source "src\EasyCon2.CLI\MockGamePad.cs"
$programSource = Join-Path $source "src\EasyCon2.CLI\Program.cs"
$previewSource = Join-Path $source "src\EasyCon2.CLI\MjpegPreviewServer.cs"
$patchAlreadyApplied = (
    (Select-String -LiteralPath $binderSource -Pattern 'ImmutableDictionary<FunctionSymbol, BoundBlockStatement>\.Empty' -Quiet) -and
    (Select-String -LiteralPath $compilationSource -Pattern 'externalGetters \?\? ImmutableDictionary<string, Func<int>>\.Empty' -Quiet) -and
    (Select-String -LiteralPath $evaluatorSource -Pattern 'ImmutableDictionary<string, Func<int>>\.Empty' -Quiet) -and
    (Select-String -LiteralPath $cliProjectSource -Pattern '<AssemblyName>EasyCon2\.CLI\.PreviewV5</AssemblyName>' -Quiet) -and
    (Select-String -LiteralPath $cliProjectSource -Pattern '<InformationalVersion>1\.6\.4-a\+9c86137c7e63bff842175470895727a5fa9bab52</InformationalVersion>' -Quiet) -and
    (Select-String -LiteralPath $mockGamePadSource -Pattern 'public void Reset\(\)' -Quiet) -and
    (Test-Path -LiteralPath $previewSource) -and
    (Select-String -LiteralPath $programSource -Pattern 'previewPortOption' -Quiet) -and
    (Select-String -LiteralPath $programSource -Pattern 'runner\.NeedILLoad \|\| previewPort > 0' -Quiet) -and
    (Select-String -LiteralPath $programSource -Pattern 'latestFrame = frame.Clone\(\)' -Quiet) -and
    (Select-String -LiteralPath $previewSource -Pattern 'class MjpegPreviewServer' -Quiet)
)
if (-not $patchAlreadyApplied) {
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace --check $patch
    if ($LASTEXITCODE -ne 0) {
        throw "EasyCon compatibility patch does not apply cleanly; the source may be partially patched"
    }
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace $patch
    if ($LASTEXITCODE -ne 0) { throw "EasyCon compatibility patch failed" }
}

$project = Join-Path $source "src\EasyCon2.CLI\EasyCon2.CLI.csproj"
dotnet restore $project -r win-x64 -p:DefaultTargetFramework=net9.0 -p:LtsTargetFramework=net9.0
if ($LASTEXITCODE -ne 0) { throw "NuGet restore failed" }

dotnet publish $project -c Release --no-restore -r win-x64 -t:Rebuild `
    -p:DefaultTargetFramework=net9.0 `
    -p:LtsTargetFramework=net9.0 `
    -p:PublishSingleFile=false `
    -p:SelfContained=true `
    -p:DebugType=None `
    -p:DebugSymbols=false `
    -o $staging
if ($LASTEXITCODE -ne 0) { throw "Compatibility runner build failed" }

$stagedRunner = Join-Path $staging $runnerFilename
if (-not (Test-Path -LiteralPath $stagedRunner)) {
    throw "Compatibility runner publish did not produce $runnerFilename"
}
$stagedVersion = (& $stagedRunner --version | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or $stagedVersion -ne "1.6.4-a+$commit") {
    throw "Staged compatibility runner failed its version check: $stagedVersion"
}

New-Item -ItemType Directory -Force -Path $output | Out-Null
Get-ChildItem -LiteralPath $staging -File -Recurse | ForEach-Object {
    $relativePath = [IO.Path]::GetRelativePath($staging, $_.FullName)
    Copy-ChangedFile $_.FullName (Join-Path $output $relativePath)
}
$runner = Join-Path $output $runnerFilename
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Compatibility runner was not copied to $runner"
}
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $runner).Hash.ToLowerInvariant()
$length = (Get-Item -LiteralPath $runner).Length
$manifest = [ordered]@{
    source_repository = "https://github.com/EasyConNS/EasyCon.git"
    source_commit = $commit
    source_version = "1.6.4-a"
    patch_id = "cli-latest-frame-ceiling-ocr-loopback-mjpeg-onedir-v6"
    description = "Continuously capture the newest DSHOW frame, share it with local OCR, and optionally expose the newest frame through a loopback-only MJPEG preview without a second capture-device owner."
    build_target = "net9.0/win-x64 self-contained onedir"
    filename = $runnerFilename
    bytes = $length
    sha256 = $hash
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output "build-manifest.json") -Encoding utf8

Write-Host "Built: $runner"
Write-Host "SHA256: $hash"
