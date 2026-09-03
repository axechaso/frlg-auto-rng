param(
    [Parameter(Mandatory = $true)]
    [string]$BuildRoot,
    [string]$Tag = "",
    [string]$Title = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Repository = "axechaso/frlg-auto-rng"
$AppVersion = (& python -c "import sys; sys.path.insert(0, r'$RepoRoot'); from app_version import APP_VERSION; print(APP_VERSION)" | Select-Object -Last 1).Trim()
if (-not $AppVersion) { throw "无法读取 app_version.py" }
if (-not $Tag) { $Tag = "v$AppVersion" }
if ($Tag -ne "v$AppVersion") { throw "发布标签必须是 v$AppVersion" }
if (-not $Title) { $Title = "FRLG Auto RNG $AppVersion 整包更新器版" }

$BuildRoot = (Resolve-Path -LiteralPath $BuildRoot).Path
$Package = Join-Path $BuildRoot "FRLG-Auto-RNG-$AppVersion-windows-x64.zip"
$Manifest = Join-Path $BuildRoot "update-manifest.json"
$ShaFile = Join-Path $BuildRoot "$([IO.Path]::GetFileName($Package)).sha256"
foreach ($path in @($Package, $Manifest, $ShaFile)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "缺少发布资产：$path"
    }
}

function Get-ReleaseByTag {
    param([Parameter(Mandatory = $true)][string]$ReleaseTag)

    # GitHub's tag endpoint does not return draft releases.  List releases and
    # match the tag instead, so draft verification and final asset checks use
    # the same release object and ID.
    $raw = (& gh api "repos/$Repository/releases?per_page=100" --paginate --slurp | Out-String)
    $apiExit = $LASTEXITCODE
    if ($apiExit -ne 0) {
        throw "无法读取 GitHub Release 列表，退出码 $apiExit"
    }
    try {
        $pages = $raw | ConvertFrom-Json
    } catch {
        throw "GitHub Release 列表不是有效 JSON"
    }
    foreach ($page in @($pages)) {
        foreach ($release in @($page)) {
            if ($release.tag_name -eq $ReleaseTag) {
                return $release
            }
        }
    }
    return $null
}

Push-Location $RepoRoot
try {
    $branch = (& git branch --show-current).Trim()
    if ($branch -ne "main") { throw "发布必须从 main 分支执行，当前为 $branch" }
    & git diff --quiet --
    if ($LASTEXITCODE -ne 0) { throw "工作区存在未提交的跟踪文件改动" }
    & git diff --cached --quiet --
    if ($LASTEXITCODE -ne 0) { throw "暂存区存在未提交改动" }
    $head = (& git rev-parse HEAD).Trim()
    $remoteHead = ((& git ls-remote origin refs/heads/main) -split "\s+")[0]
    if (-not $remoteHead -or $remoteHead -ne $head) {
        throw "origin/main 尚未指向当前提交 $head"
    }

    # A keyring timeout from `gh auth status` is not enough to declare auth
    # invalid; use the direct API check required by the repository policy.
    $loginOutput = & gh api user --jq .login 2>&1
    $loginExit = $LASTEXITCODE
    if ($loginExit -ne 0 -or ($loginOutput | Out-String).Trim() -ne "axechaso") {
        throw "GitHub API 认证检查失败；请区分网络/keyring 超时与 Bad credentials。"
    }

    $manifestObject = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
    if ($manifestObject.schema -ne 1 -or $manifestObject.version -ne $AppVersion -or
        $manifestObject.version_code -le 0 -or
        $manifestObject.package -ne [IO.Path]::GetFileName($Package)) {
        throw "更新清单与当前 $AppVersion 发布包不一致"
    }
    $hash = (Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $manifestObject.sha256 -or (Get-Item -LiteralPath $Package).Length -ne $manifestObject.bytes) {
        throw "发布包大小或 SHA-256 与更新清单不一致"
    }
    $shaText = (Get-Content -LiteralPath $ShaFile -Raw).Trim()
    if ($shaText -ne "$hash  $([IO.Path]::GetFileName($Package))") {
        throw "SHA-256 文件内容不一致"
    }

    $ciJson = (& gh run list --repo $Repository --commit $head --limit 20 --json databaseId,headSha,status,conclusion | Out-String) | ConvertFrom-Json
    $successful = @($ciJson | Where-Object {
        $_.headSha -eq $head -and $_.status -eq "completed" -and $_.conclusion -eq "success"
    })
    if ($successful.Count -eq 0) { throw "当前提交没有成功的 GitHub Actions 检查" }

    $tagExists = & git ls-remote --exit-code origin "refs/tags/$Tag" 2>$null
    if ($LASTEXITCODE -eq 0 -and $tagExists) { throw "远程标签已存在：$Tag，不自动覆盖" }
    $existingRelease = Get-ReleaseByTag $Tag
    if ($existingRelease) { throw "GitHub Release 已存在：$Tag，不自动覆盖" }

    $assetNames = @(
        [IO.Path]::GetFileName($Package),
        "update-manifest.json",
        [IO.Path]::GetFileName($ShaFile)
    )
    if ($DryRun) {
        Write-Host "DRY RUN：将创建草稿 $Tag 并上传 $($assetNames -join ', ')"
        return
    }

    & gh release create $Tag --repo $Repository --draft --title $Title --notes "FRLG Auto RNG $AppVersion。整包绿色版，支持后续版本应用内更新。"
    if ($LASTEXITCODE -ne 0) { throw "创建草稿 Release 失败" }
    try {
        & gh release upload $Tag $Package $Manifest $ShaFile --repo $Repository
        if ($LASTEXITCODE -ne 0) { throw "上传 Release 资产失败；草稿已保留" }
        $release = Get-ReleaseByTag $Tag
        if (-not $release) { throw "创建后找不到 Release：$Tag；草稿已保留" }
        $actual = @($release.assets | ForEach-Object { $_.name })
        foreach ($name in $assetNames) {
            if ($actual -notcontains $name) { throw "Release 缺少资产：$name；草稿已保留" }
        }
        foreach ($asset in $release.assets) {
            if ($asset.name -eq [IO.Path]::GetFileName($Package) -and $asset.size -ne (Get-Item -LiteralPath $Package).Length) {
                throw "Release ZIP 大小回读不一致；草稿已保留"
            }
        }
        & gh api "repos/$Repository/releases/$($release.id)" -X PATCH -f draft=false -f make_latest=true
        if ($LASTEXITCODE -ne 0) { throw "发布正式 Release 失败；草稿已保留" }
        Write-Host "已发布：https://github.com/$Repository/releases/tag/$Tag"
    } catch {
        Write-Error "发布未完成，草稿 Release 已保留供检查。"
        throw
    }
} finally {
    Pop-Location
}
