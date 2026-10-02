# Windows 绿色版

使用 `tools\build_windows_release.ps1` 生成发布包。构建机使用项目自己的 `.venv`，脚本锁定安装 PyInstaller 6.15.0、PySide6 6.11.2 与 truststore 0.10.4；使用发布包的用户不需要安装 Python 或任何 Python 依赖。当前发布合同为 `0.9.4.1 / 2026092701`，正式界面仅为 PySide6，发行目录不包含旧 Tk、Tcl/Tk 或 tkinterdnd2 运行时。

```powershell
.\tools\build_windows_release.ps1 `
  -BuildTag pyside6-0-9-4-1-20260927-r1 `
  -EasyConPublish 'D:\Download\伊机控-EasyCon-v1.6.4alpha测试版-260518\publish' `
  -LocalAssets .\local_assets `
  -NotesFile .\docs\releases\v0.9.4.1.md
```

脚本默认从现有 `dist\*\easycon\publish` 查找 EasyCon 1.6.4-a。也可以明确指定：

```powershell
.\tools\build_windows_release.ps1 -EasyConPublish 'D:\EasyCon\publish'
```

输出位于 `.build\windows-release-pyside6-0-9-4-1-20260927-r1\FRLG-Auto-RNG-0.9.4.1-windows-x64`，同时生成同名 ZIP、`update-manifest.json`、`.sha256`、`incremental-release-assets` 和 `gitee-release-assets`。增量资源生成后逐文件与完整 ZIP 核对，构建末尾再执行冻结版本探针和隔离数据目录下的 PySide6 截图冒烟。发布包是绿色文件夹，不应把 `.venv`、源码或 Python 安装包一起复制给用户。配置、日志和运行时生成的 ECS 工程会写入 `%LOCALAPPDATA%\FRLG-Auto-RNG`。

按当前源码构建的绿色版会内置 Seed 表更新器。用户在 GUI 点击“检查/更新 Seed 表”即可下载 Ten Lines 官方火红/叶绿 NX 二进制表、生成对应 EasyCon ECS 表并执行真实 1.6.4-a `format` 校验，不需要系统 Python，也不依赖外部 `Tools\update_*.py`。验证后的四个文件写入 `%LOCALAPPDATA%\FRLG-Auto-RNG\seed_tables\current`，上一版保留为 `previous`；生成运行工程时会自动覆盖两份 `lib` Seed 表。

当前使用 `onedir` 而不是单文件模式，因为 EasyCon、Tessdata、识图标签和兼容运行器体积较大，文件夹版启动更快、杀毒误报更少，也便于 EasyCon 运行时访问旁边的资源。

## 程序增量更新

绿色版包内包含 `FRLG-Auto-RNG-Updater.exe`。启动后会在后台检查公开仓库的最新稳定 Release，每 24 小时最多自动检查一次；“检查程序更新”按钮可手动触发。程序更新源可选“自动（GitHub 优先）”“GitHub”或“Gitee”。自动模式下，GitHub 检查成功时不访问 Gitee，只有 GitHub 检查失败才读取 Gitee 最新正式 Release；手动选择 GitHub 或 Gitee 时只使用指定源，不跨源回退。

包含本次更新器改动的构建优先读取 `incremental-manifest.json`：按文件大小和 SHA-256 比对当前安装目录，再显示实际需下载的大小及可复用文件数，用户确认后才下载数据包。未变化的文件直接复制到独立暂存目录；缺失、损坏、新增或变化的文件由所需数据包重建。新目录只包含清单中的文件，因此新版删除的旧文件不会残留。无须指定某个旧版本作为补丁基线。

传输单位是压缩小包：大于等于 1 MiB 的文件独立分包，小文件按路径分为 16 个稳定分组；每包原始数据最多 16 MiB，压缩后最多约 16.1 MiB。修改小脚本不会把未变化的大型运行库或 OCR 模型带入下载。变化文件所在的小包可能携带少量未变化的小文件，因此这是文件比对、小包传输的增量更新，不是逐字节二进制差分。数据包下载完成并校验后按内容摘要缓存到用户目录 `updates/bundles`；中断或取消只清理未完成的小包，重试复用已完成的小包，不依赖服务器支持 HTTP Range。尚未完成的单个小包仍从头下载。

增量清单必须与完整更新清单的版本、版本码、完整 ZIP 摘要和解压大小一致；每包校验压缩大小与 SHA-256，解压有大小上限，每个组装后的文件再次校验大小与 SHA-256。自动模式的 GitHub → Gitee 下载回退还要求两边的增量清单完全一致。手动模式仍不跨源。清单缺包或校验失败时报告错误，不悄悄改成全量下载。

旧版更新器仍只认识完整 ZIP / Gitee 90 MiB 分卷，需要先按旧流程升级一次才能获得增量能力。新版遇到未提供增量清单的历史 Release 时，会在确认框明确告知需下载完整包。原 schema 1 整包清单字段保持不变，完整包和旧分卷继续发布，供旧客户端升级和手动安装。增量更新不会修复 Gitee API 自身返回的 403；服务器拒绝请求时仍需检查其可用性。

程序更新始终安装完整的新版本，不提供运行中独立切换标签、Seed 表或脚本的热更新。标签可通过“标签”页导入设备专用覆盖，Seed 表继续使用独立的 Seed 表更新器。

安装会在主程序退出后由独立更新器完成目录交换；交换失败或新版启动确认超时会自动恢复旧目录。`%LOCALAPPDATA%\FRLG-Auto-RNG` 下的配置、日志、TID/SID 进度、Seed 表和设备标签覆盖不参与替换。EasyCon 或搜索流程运行时禁止安装。

现有 `0.2.2` 绿色包可通过原有整包更新器直接升级到 `0.9`，因为主程序、独立更新器、schema 1 清单和健康探针合同保持不变。`0.2.1` 或更早版本若受旧证书链问题影响，应手工安装 `0.2.2` 或 `0.9`，不得关闭 TLS 验证。源码运行模式不会联网自更新。

## 发布 `0.9.4.1`

确认 `main` 已推送且 GitHub Actions 成功后运行：

```powershell
.\tools\publish_windows_release.ps1 `
  -BuildRoot .build\windows-release-pyside6-0-9-4-1-20260927-r1 `
  -Tag v0.9.4.1 `
  -Title "FRLG Auto RNG 0.9.4.1 PySide6版" `
  -NotesFile .\docs\releases\v0.9.4.1.md
```

脚本先验证完整包与所有增量资源内容一致，再创建草稿 Release，上传完整 ZIP、`update-manifest.json`、SHA 文件及 `incremental-release-assets` 内清单引用的全部资源，并回读资产名称和增量包大小。校验未完成时草稿保持不公开，不会覆盖已有 tag。

### 手工上传 Gitee 更新源

每次执行 `build_windows_release.ps1` 都会在构建根目录生成 `gitee-release-assets`。该目录只包含需要手工上传到 Gitee Release 的文件：

```text
gitee-update-manifest.json
incremental-manifest.json
update-data-<SHA256>.bin
...
FRLG-Auto-RNG-<版本>-windows-x64.zip.001
FRLG-Auto-RNG-<版本>-windows-x64.zip.002
...
```

兼容旧客户端的完整 ZIP 默认按每卷 90 MiB 切分；增量清单与增量数据包和 GitHub 完全相同。Gitee 发布时须使用与 GitHub 完全相同的 `v<版本>` 标签，创建正式 Release，并把 `gitee-release-assets` 内的全部文件原名上传；不要漏传、改名或只上传旧分卷而漏掉增量资源。无需把完整 ZIP、GitHub 的 `update-manifest.json` 或 `.sha256` 再上传到 Gitee。用户负责在网页中上传这些已准备好的资产，构建和发布脚本不会代替用户登录或发布 Gitee Release。
