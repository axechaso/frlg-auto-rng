# Windows 绿色版

使用 `tools\build_windows_release.ps1` 生成发布包。构建机只需要项目自己的 `.venv` 和一次网络安装 PyInstaller；使用发布包的用户不需要安装 Python、pygame 或任何 Python 依赖。当前发布合同为 `0.2`。

```powershell
.\tools\build_windows_release.ps1 `
  -BuildTag updater-0-2 `
  -EasyConPublish 'C:\Users\axenx\Downloads\伊机控-EasyCon-v1.6.4alpha测试版-260518\publish' `
  -LocalAssets .\local_assets
```

脚本默认从现有 `dist\*\easycon\publish` 查找 EasyCon 1.6.4-a。也可以明确指定：

```powershell
.\tools\build_windows_release.ps1 -EasyConPublish 'D:\EasyCon\publish'
```

输出位于 `.build\windows-release-updater-0-2\FRLG-Auto-RNG-0.2-windows-x64`，同时生成同名 ZIP、`update-manifest.json` 和 `.sha256` 文件。发布包是绿色文件夹，不应把 `.venv`、源码或 Python 安装包一起复制给用户。配置、日志和运行时生成的 ECS 工程会写入 `%LOCALAPPDATA%\FRLG-Auto-RNG`。

按当前源码构建的绿色版会内置 Seed 表更新器。用户在 GUI 点击“检查/更新 Seed 表”即可下载 Ten Lines 官方火红/叶绿 NX 二进制表、生成对应 EasyCon ECS 表并执行真实 1.6.4-a `format` 校验，不需要系统 Python，也不依赖外部 `Tools\update_*.py`。验证后的四个文件写入 `%LOCALAPPDATA%\FRLG-Auto-RNG\seed_tables\current`，上一版保留为 `previous`；生成运行工程时会自动覆盖两份 `lib` Seed 表。

当前使用 `onedir` 而不是单文件模式，因为 EasyCon、Tessdata、识图标签和兼容运行器体积较大，文件夹版启动更快、杀毒误报更少，也便于 EasyCon 运行时访问旁边的资源。

## 程序整包更新

`0.2` 包内包含 `FRLG-Auto-RNG-Updater.exe`。冻结绿色版启动后会在后台检查公开仓库的最新稳定 Release，每 24 小时最多自动检查一次；“检查程序更新”按钮可手动触发。发现新版本时只显示确认对话框，用户确认后才下载完整 ZIP，并校验清单、文件大小、SHA-256、ZIP 路径和内嵌版本。

安装会在主程序退出后由独立更新器完成目录交换；交换失败或新版启动确认超时会自动恢复旧目录。`%LOCALAPPDATA%\FRLG-Auto-RNG` 下的配置、日志、TID/SID 进度、Seed 表和设备标签覆盖不参与替换。EasyCon 或搜索流程运行时禁止安装。

现有 `1.1.8` 或更早绿色包没有这个更新器，必须先手动解压安装 `0.2`；从 `0.2` 开始，后续正式 Release 才能使用应用内更新。源码运行模式不会联网自更新。

## 发布 `0.2`

确认 `main` 已推送且 GitHub Actions 成功后运行：

```powershell
.\tools\publish_windows_release.ps1 `
  -BuildRoot .build\windows-release-updater-0-2 `
  -Tag v0.2 `
  -Title "FRLG Auto RNG 0.2 整包更新器版"
```

脚本会先创建草稿 Release，上传完整 ZIP、`update-manifest.json` 和 SHA 文件，并回读三项资产名称与大小；校验未完成时草稿保持不公开，不会覆盖已有 tag。
