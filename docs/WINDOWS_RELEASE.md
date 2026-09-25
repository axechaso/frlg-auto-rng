# Windows 绿色版

使用 `tools\build_windows_release.ps1` 生成发布包。构建机使用项目自己的 `.venv`，脚本锁定安装 PyInstaller 6.15.0、PySide6 6.11.2 与 truststore 0.10.4；使用发布包的用户不需要安装 Python 或任何 Python 依赖。当前发布合同为 `0.9.4 / 2026092501`，正式界面仅为 PySide6，发行目录不包含旧 Tk、Tcl/Tk 或 tkinterdnd2 运行时。

```powershell
.\tools\build_windows_release.ps1 `
  -BuildTag pyside6-0-9-4-20260925-r5 `
  -EasyConPublish 'C:\Users\axenx\Downloads\伊机控-EasyCon-v1.6.4alpha测试版-260518\publish' `
  -LocalAssets .\local_assets `
  -NotesFile .\docs\releases\v0.9.4.md
```

脚本默认从现有 `dist\*\easycon\publish` 查找 EasyCon 1.6.4-a。也可以明确指定：

```powershell
.\tools\build_windows_release.ps1 -EasyConPublish 'D:\EasyCon\publish'
```

输出位于 `.build\windows-release-pyside6-0-9-4-20260925-r5\FRLG-Auto-RNG-0.9.4-windows-x64`，同时生成同名 ZIP、`update-manifest.json`、`.sha256` 文件和 `gitee-release-assets` 目录。构建末尾会执行冻结版本探针和隔离数据目录下的 PySide6 截图冒烟。发布包是绿色文件夹，不应把 `.venv`、源码或 Python 安装包一起复制给用户。配置、日志和运行时生成的 ECS 工程会写入 `%LOCALAPPDATA%\FRLG-Auto-RNG`。

按当前源码构建的绿色版会内置 Seed 表更新器。用户在 GUI 点击“检查/更新 Seed 表”即可下载 Ten Lines 官方火红/叶绿 NX 二进制表、生成对应 EasyCon ECS 表并执行真实 1.6.4-a `format` 校验，不需要系统 Python，也不依赖外部 `Tools\update_*.py`。验证后的四个文件写入 `%LOCALAPPDATA%\FRLG-Auto-RNG\seed_tables\current`，上一版保留为 `previous`；生成运行工程时会自动覆盖两份 `lib` Seed 表。

当前使用 `onedir` 而不是单文件模式，因为 EasyCon、Tessdata、识图标签和兼容运行器体积较大，文件夹版启动更快、杀毒误报更少，也便于 EasyCon 运行时访问旁边的资源。

## 程序整包更新

`0.9` 包内包含 `FRLG-Auto-RNG-Updater.exe`。冻结 PySide6 绿色版启动后会在后台检查公开仓库的最新稳定 Release，每 24 小时最多自动检查一次；“检查程序更新”按钮可手动触发。程序更新源可选“自动（GitHub 优先）”“GitHub”或“Gitee”。自动模式下，GitHub 检查成功时不访问 Gitee，只有 GitHub 检查失败才读取 Gitee 最新正式 Release；手动选择 GitHub 或 Gitee 时只使用指定源，不跨源回退。发现新版本时只显示确认对话框，用户确认后才下载完整 ZIP，并校验清单、文件大小、SHA-256、ZIP 路径和内嵌版本。

GitHub 仍发布完整 ZIP、`update-manifest.json` 和 SHA 文件。在自动模式下，若 GitHub ZIP 下载途中发生网络或证书错误，更新器会读取 Gitee 的同版本分卷；只有版本、版本码、包名、完整大小、完整 SHA-256 和解压大小全部与已验证的 GitHub 清单一致才允许接续。手动 GitHub 模式下载失败时直接报告错误，不自动访问 Gitee；手动 Gitee 模式直接校验并下载 Gitee 分卷。Gitee 每个分卷独立校验大小与 SHA-256，合并后再次校验完整 ZIP。校验失败、分卷缺失、顺序错误或镜像版本不一致都会删除临时文件并拒绝安装，不会为了切换源而关闭 TLS 或完整性检查。

这三个更新源模式都只用于完整程序包，不提供标签、Seed 表或单个脚本的独立热更新。标签可通过“标签”页导入设备专用覆盖，Seed 表继续使用独立的 Seed 表更新器；两者都不是程序更新源的增量补丁。已发布的 `0.9.2` 二进制不含更新源选择逻辑；`0.9.3` 及后续构建包含该功能。

安装会在主程序退出后由独立更新器完成目录交换；交换失败或新版启动确认超时会自动恢复旧目录。`%LOCALAPPDATA%\FRLG-Auto-RNG` 下的配置、日志、TID/SID 进度、Seed 表和设备标签覆盖不参与替换。EasyCon 或搜索流程运行时禁止安装。

现有 `0.2.2` 绿色包可通过原有整包更新器直接升级到 `0.9`，因为主程序、独立更新器、schema 1 清单和健康探针合同保持不变。`0.2.1` 或更早版本若受旧证书链问题影响，应手工安装 `0.2.2` 或 `0.9`，不得关闭 TLS 验证。源码运行模式不会联网自更新。

## 发布 `0.9.4`

确认 `main` 已推送且 GitHub Actions 成功后运行：

```powershell
.\tools\publish_windows_release.ps1 `
  -BuildRoot .build\windows-release-pyside6-0-9-4-20260925-r5 `
  -Tag v0.9.4 `
  -Title "FRLG Auto RNG 0.9.4 PySide6版" `
  -NotesFile .\docs\releases\v0.9.4.md
```

脚本会先创建草稿 Release，上传完整 ZIP、`update-manifest.json` 和 SHA 文件，并回读三项资产名称与大小；校验未完成时草稿保持不公开，不会覆盖已有 tag。

### 手工上传 Gitee 分卷备用源

每次执行 `build_windows_release.ps1` 都会在构建根目录生成 `gitee-release-assets`。该目录只包含需要手工上传到 Gitee Release 的文件：

```text
gitee-update-manifest.json
FRLG-Auto-RNG-<版本>-windows-x64.zip.001
FRLG-Auto-RNG-<版本>-windows-x64.zip.002
...
```

完整 ZIP 默认按每卷 90 MiB 切分。Gitee 发布时须使用与 GitHub 完全相同的 `v<版本>` 标签，创建正式 Release，并把 `gitee-release-assets` 内的全部文件原名上传；不要漏传、改名或只上传分卷而漏掉清单。无需把完整 ZIP、GitHub 的 `update-manifest.json` 或 `.sha256` 再上传到 Gitee。用户负责在网页中上传这些已准备好的资产，构建和发布脚本不会代替用户登录或发布 Gitee Release。
