param([string]$OutputDirectory = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $root 'assets\clock_test' }
$source = Join-Path $PSScriptRoot 'clock_test\clock_test.cpp'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Missing MSVC x64 Build Tools.' }
$version = (Get-Content (Join-Path $vs 'VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt')).Trim()
$compiler = Join-Path $vs "VC\Tools\MSVC\$version\bin\Hostx64\x64\cl.exe"
$sdk = Get-ItemPropertyValue 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots' KitsRoot10
$sdkVersion = (Get-ChildItem (Join-Path $sdk 'Include') -Directory | Sort-Object Name -Descending | Select-Object -First 1).Name
$oldInclude, $oldLib = $env:INCLUDE, $env:LIB
$scratch = Join-Path $root ('.tmp\clock-build-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch,$OutputDirectory -Force | Out-Null
try {
    $env:INCLUDE = @((Join-Path $vs "VC\Tools\MSVC\$version\include"),
        (Join-Path $sdk "Include\$sdkVersion\ucrt"), (Join-Path $sdk "Include\$sdkVersion\shared"),
        (Join-Path $sdk "Include\$sdkVersion\um")) -join ';'
    $env:LIB = @((Join-Path $vs "VC\Tools\MSVC\$version\lib\x64"),
        (Join-Path $sdk "Lib\$sdkVersion\ucrt\x64"), (Join-Path $sdk "Lib\$sdkVersion\um\x64")) -join ';'
    $dll = Join-Path $OutputDirectory 'frlg_clock_test.dll'
    & $compiler /nologo /O2 /W4 /WX /MT /LD /std:c++17 /Brepro $source "/Fo$scratch\clock.obj" "/Fe$dll" /link /INCREMENTAL:NO /OPT:REF /OPT:ICF "/IMPLIB:$scratch\clock.lib" /Brepro
    if ($LASTEXITCODE -ne 0) { throw "Native clock build failed: $LASTEXITCODE" }
    $manifest = [ordered]@{
        schema = 'FRLG_CLOCK_TEST_NATIVE_V1'; abi = 1; machine = 'windows-x64';
        clock = 'QueryPerformanceCounter'; scheduler = 'high_resolution_waitable_timer_2ms_spin';
        max_sleep_slice_ms = 8; wait_timeout_ms = 10; spin_tail_ms = 2;
        eontimer_commit = 'ead211d6e4251c4f08345cc9e56e76d3cb2a29bd';
        source_sha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant();
        dll_sha256 = (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant();
        dll_bytes = (Get-Item -LiteralPath $dll).Length
    }
    # A build-generated manifest, not a hand-edited configuration.
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'build-manifest.json'), ($manifest | ConvertTo-Json) + "`n", [Text.UTF8Encoding]::new($false))
    Get-Item -LiteralPath $dll | Select-Object FullName,Length
} finally {
    $env:INCLUDE, $env:LIB = $oldInclude, $oldLib
}
