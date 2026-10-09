$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root ".build\easycon164a-input-state-v2-source"
$output = Join-Path $root "runtime_backend\easycon164a-cli-gui-rounding-selfcontained"
$buildRoot = [IO.Path]::GetFullPath((Join-Path $root ".build"))
$patch = Join-Path $PSScriptRoot "patches\easycon164a-cli-gui-rounding-next.patch"
$labelSupervisionPatch = Join-Path $PSScriptRoot "patches\easycon164a-label-supervision.patch"
$labelSupervisionV8Patch = Join-Path $PSScriptRoot "patches\easycon164a-label-supervision-v8.patch"
$labelSupervisionV9Patch = Join-Path $PSScriptRoot "patches\easycon164a-label-supervision-v9.patch"
$stageLogFilterPatch = Join-Path $PSScriptRoot "patches\easycon164a-stage-log-filter.patch"
$inputStatePatch = Join-Path $PSScriptRoot "patches\easycon164a-input-state-v1.patch"
$inputStatePreviewVideoPatch = Join-Path $PSScriptRoot "patches\easycon164a-input-state-preview-video-v1.patch"
$inputStateJsonPatch = Join-Path $PSScriptRoot "patches\easycon164a-input-state-json-v2.patch"
$synchronousCapturePatch = Join-Path $PSScriptRoot "patches\easycon164a-synchronous-capture-v1.patch"
$synchronizedFrameSource = Join-Path $PSScriptRoot "runner_capture\SynchronizedFrameSource.cs"
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
    (Select-String -LiteralPath $programSource -Pattern 'runner\.NeedILLoad \|\| (previewPort > 0|previewVideo)' -Quiet) -and
    ((Select-String -LiteralPath $programSource -SimpleMatch 'latestFrame = frame.Clone()' -Quiet) -or
     (Select-String -LiteralPath $programSource -SimpleMatch 'latestFrame = captured.Frame.Clone()' -Quiet)) -and
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

$supervisorSource = Join-Path $source "src\EasyCon2.CLI\LabelFaultSupervisor.cs"
$labelPatchAlreadyApplied = (
    (Test-Path -LiteralPath $supervisorSource) -and
    (Select-String -LiteralPath $programSource -Pattern 'new LabelFaultSupervisor\(' -Quiet) -and
    (Select-String -LiteralPath $programSource -Pattern 'verifyLabelCommand' -Quiet) -and
    (Select-String -LiteralPath $programSource -Pattern 'incidentDirectoryOption' -Quiet) -and
    (Select-String -LiteralPath $programSource -Pattern 'save-frames-dir' -Quiet) -and
    (Select-String -LiteralPath (Join-Path $source "src\EasyCon2.CLI\ConsoleOutAdapter.cs") -Pattern 'LineWritten' -Quiet)
)
if (-not $labelPatchAlreadyApplied) {
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace --check $labelSupervisionPatch
    if ($LASTEXITCODE -ne 0) {
        throw "EasyCon label supervision patch does not apply cleanly; the source may be partially patched"
    }
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace $labelSupervisionPatch
    if ($LASTEXITCODE -ne 0) { throw "EasyCon label supervision patch failed" }
}

$labelSupervisionV8AlreadyApplied = (
    (Test-Path -LiteralPath $supervisorSource) -and
    (Select-String -LiteralPath $supervisorSource -Pattern 'UpdateThreshold\(int threshold\)' -Quiet) -and
    (Select-String -LiteralPath $supervisorSource -Pattern 'MarkProgress\(long now, DateTimeOffset atUtc\)' -Quiet) -and
    (Select-String -LiteralPath $supervisorSource -Pattern 'marker.TimeoutMs < 0' -Quiet) -and
    (Select-String -LiteralPath $supervisorSource -Pattern 'stage.Marker.TimeoutMs > 0' -Quiet)
)
if (-not $labelSupervisionV8AlreadyApplied) {
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace --check $labelSupervisionV8Patch
    if ($LASTEXITCODE -ne 0) {
        throw "EasyCon label supervision v8 patch does not apply cleanly; the source may be partially patched"
    }
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace $labelSupervisionV8Patch
    if ($LASTEXITCODE -ne 0) { throw "EasyCon label supervision v8 patch failed" }
}

$labelSupervisionV9AlreadyApplied = (
    (Select-String -LiteralPath $programSource -Pattern 'labelSupervisionOption' -Quiet) -and
    (Select-String -LiteralPath $programSource -Pattern 'if \(labelSupervision\)' -Quiet) -and
    (Select-String -LiteralPath $programSource -Pattern 'supervisor\?\.ObserveMatch' -Quiet)
)
if (-not $labelSupervisionV9AlreadyApplied) {
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace --check $labelSupervisionV9Patch
    if ($LASTEXITCODE -ne 0) {
        throw "EasyCon label supervision v9 patch does not apply cleanly; the source may be partially patched"
    }
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace $labelSupervisionV9Patch
    if ($LASTEXITCODE -ne 0) { throw "EasyCon label supervision v9 patch failed" }
}

$stageLogFilterApplied = Select-String -LiteralPath (Join-Path $source "src\EasyCon2.CLI\ConsoleOutAdapter.cs") -Pattern 'message\.Contains\("FRLG_STAGE\|"' -Quiet
if (-not $stageLogFilterApplied) {
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace --check $stageLogFilterPatch
    if ($LASTEXITCODE -ne 0) {
        throw "EasyCon stage log filter patch does not apply cleanly; the source may be partially patched"
    }
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace $stageLogFilterPatch
    if ($LASTEXITCODE -ne 0) { throw "EasyCon stage log filter patch failed" }
}

$inputStateBufferSource = Join-Path $source "src\EasyCon.Device\InputStateBuffer.cs"
$deviceLoopSource = Join-Path $source "src\EasyCon.Device\NintendoSwitchPriv.cs"
$inputStateCoreAlreadyApplied = (
    (Test-Path -LiteralPath $inputStateBufferSource) -and
    (Select-String -LiteralPath $deviceLoopSource -Pattern 'InputStateBuffer\.Publish\(sentButton' -Quiet) -and
    (Select-String -LiteralPath $previewSource -Pattern 'route == "/input-state"' -Quiet) -and
    (Select-String -LiteralPath $previewSource -Pattern 'route == "/capabilities"' -Quiet) -and
    (Select-String -LiteralPath $programSource -Pattern 'inputSessionIdOption' -Quiet) -and
    (Select-String -LiteralPath $programSource -Pattern 'InputStateBuffer\.Configure' -Quiet)
)
if (-not $inputStateCoreAlreadyApplied) {
    $inputStatePatchesToApply = @($inputStatePatch, $inputStatePreviewVideoPatch)
} else {
    $inputStatePreviewVideoAlreadyApplied = (
        (Select-String -LiteralPath $programSource -Pattern 'previewVideoOption' -Quiet) -and
        (Select-String -LiteralPath $programSource -Pattern 'runScriptCommand\.Options\.Add\(previewVideoOption\)' -Quiet) -and
        (Select-String -LiteralPath $programSource -Pattern 'parseResult\.GetValue\(previewVideoOption\)' -Quiet) -and
        (Select-String -LiteralPath $programSource -Pattern 'runner\.NeedILLoad \|\| previewVideo' -Quiet)
    )
    if ($inputStatePreviewVideoAlreadyApplied) {
        $inputStatePatchesToApply = @()
    } else {
        $inputStatePatchesToApply = @($inputStatePreviewVideoPatch)
    }
}
foreach ($inputStatePatchToApply in $inputStatePatchesToApply) {
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace --check $inputStatePatchToApply
    if ($LASTEXITCODE -ne 0) {
        throw "EasyCon input state patch does not apply cleanly; the source may be partially patched"
    }
    git -c "safe.directory=$source" -C $source apply --ignore-space-change --ignore-whitespace $inputStatePatchToApply
    if ($LASTEXITCODE -ne 0) { throw "EasyCon input state patch failed" }
}

$project = Join-Path $source "src\EasyCon2.CLI\EasyCon2.CLI.csproj"
$jsonV2Applied = (
    (Select-String -LiteralPath $inputStateBufferSource -SimpleMatch '[property: JsonPropertyName("left_stick")] int[] LeftStick' -Quiet) -and
    (Select-String -LiteralPath $inputStateBufferSource -SimpleMatch '[property: JsonPropertyName("right_stick")] int[] RightStick' -Quiet) -and
    (Select-String -LiteralPath $inputStateBufferSource -SimpleMatch 'new int[] { report.LX, report.LY }' -Quiet) -and
    (Select-String -LiteralPath $inputStateBufferSource -SimpleMatch 'new int[] { report.RX, report.RY }' -Quiet)
)
if (-not $jsonV2Applied) {
    git -c "safe.directory=$source" -C $source apply --check $inputStateJsonPatch
    if ($LASTEXITCODE -ne 0) {
        git -c "safe.directory=$source" -C $source diff -- src/EasyCon.Device/InputStateBuffer.cs
        throw "Input-state JSON v2 patch cannot apply cleanly; preserve and inspect the source differences"
    }
    git -c "safe.directory=$source" -C $source apply $inputStateJsonPatch
    if ($LASTEXITCODE -ne 0) { throw "Input-state JSON v2 patch failed" }
}
$synchronousCaptureApplied = (
    (Select-String -LiteralPath $programSource -SimpleMatch 'frameSource = new SynchronizedFrameSource<Mat>(' -Quiet) -and
    (Select-String -LiteralPath $programSource -SimpleMatch 'var captured = frameSource!.Read(runCancellation.Token);' -Quiet) -and
    (Select-String -LiteralPath $programSource -SimpleMatch 'snapshot, captured.Sequence, captured.CompletedTicks' -Quiet) -and
    (Select-String -LiteralPath $programSource -SimpleMatch '() => frameSource!.Read(runCancellation.Token)?.Frame' -Quiet)
)
if (-not $synchronousCaptureApplied) {
    git -c "safe.directory=$source" -C $source apply --check $synchronousCapturePatch
    if ($LASTEXITCODE -ne 0) { throw "Synchronous capture patch cannot apply cleanly; preserve the source and inspect its differences" }
    git -c "safe.directory=$source" -C $source apply $synchronousCapturePatch
    if ($LASTEXITCODE -ne 0) { throw "Synchronous capture patch failed" }
}
Copy-ChangedFile -SourcePath $synchronizedFrameSource -DestinationPath (Join-Path $source 'src\EasyCon2.CLI\SynchronizedFrameSource.cs')

dotnet restore $project -r win-x64 -p:DefaultTargetFramework=net9.0 -p:LtsTargetFramework=net9.0
if ($LASTEXITCODE -ne 0) { throw "NuGet restore failed" }

dotnet publish $project -c Release --no-restore -r win-x64 -t:Rebuild `
    -p:DefaultTargetFramework=net9.0 `
    -p:LtsTargetFramework=net9.0 `
    -p:PublishSingleFile=false `
    -p:SelfContained=true `
    -p:IncludeSourceRevisionInInformationalVersion=false `
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

$verification = Join-Path $buildRoot "protocol-verification-$PID"
New-Item -ItemType Directory -Force -Path $verification | Out-Null
$samples = Join-Path $verification "assembly-samples.json"
dotnet run --project (Join-Path $PSScriptRoot "EasyConInputStateProtocolCheck\EasyConInputStateProtocolCheck.csproj") -p:EasyConDir=$staging -- $samples
if ($LASTEXITCODE -ne 0) { throw "Published Device assembly protocol verification failed" }
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
& $python (Join-Path $PSScriptRoot "verify_easycon_protocol.py") --runner $stagedRunner --samples $samples --output $verification
if ($LASTEXITCODE -ne 0) { throw "Staged runner HTTP/PRINT/GUI verification failed; current runner preserved" }
$captureSamples = Join-Path $verification "synchronized-capture.json"
dotnet run --project (Join-Path $PSScriptRoot "EasyConFrameCaptureCheck\EasyConFrameCaptureCheck.csproj") -p:EasyConDir=$staging -- $captureSamples
if ($LASTEXITCODE -ne 0) { throw "Published synchronized capture verification failed; current runner preserved" }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $stagedRunner).Hash.ToLowerInvariant()
$length = (Get-Item -LiteralPath $stagedRunner).Length
$files = [ordered]@{}
foreach ($name in @("EasyCon.Device.dll", "$assemblyName.dll")) {
    $file = Join-Path $staging $name
    $files[$name] = @{ sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLowerInvariant(); bytes = (Get-Item -LiteralPath $file).Length }
}
$manifest = [ordered]@{
    source_repository = "https://github.com/EasyConNS/EasyCon.git"
    source_commit = $commit
    source_version = "1.6.4-a"
    patch_id = "easycon164a-synchronous-capture-v11-stage-log-filter-input-state-v2"
    description = "Read a fresh camera frame synchronously for every label/OCR request, serialize it with background draining, bind match diagnostics to the actual frame, and preserve shared preview, fault supervision and read-only input-state reporting."
    build_target = "net9.0/win-x64 self-contained onedir"
    filename = $runnerFilename
    bytes = $length
    sha256 = $hash
    files = $files
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $staging "build-manifest.json") -Encoding utf8

$outputFull = [IO.Path]::GetFullPath($output)
$backendRoot = [IO.Path]::GetFullPath((Join-Path $root "runtime_backend"))
if (-not $outputFull.StartsWith($backendRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
    -not $staging.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Runner swap paths are outside the intended workspace"
}
$active = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($outputFull + '\', [StringComparison]::OrdinalIgnoreCase) }
if ($active) { throw "Current compatibility runner is active; stop it before updating. Staged output is preserved at $staging" }
$oldTessdata = Join-Path $output "Tessdata"
if (Test-Path -LiteralPath $oldTessdata) {
    $stagedTessdata = Join-Path $staging 'Tessdata'
    New-Item -ItemType Directory -Path $stagedTessdata -Force | Out-Null
    Get-ChildItem -LiteralPath $oldTessdata | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $stagedTessdata -Recurse -Force
    }
}
$backup = $outputFull + ".before-synchronous-capture-" + [DateTime]::UtcNow.ToString("yyyyMMddHHmmss")
New-Item -ItemType Directory -Force -Path $backendRoot | Out-Null
try {
    if (Test-Path -LiteralPath $outputFull) { Move-Item -LiteralPath $outputFull -Destination $backup }
    Move-Item -LiteralPath $staging -Destination $outputFull
} catch {
    if ((Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $outputFull)) { Move-Item -LiteralPath $backup -Destination $outputFull }
    throw
}
$runner = Join-Path $output $runnerFilename

Write-Host "Built: $runner"
Write-Host "SHA256: $hash"
