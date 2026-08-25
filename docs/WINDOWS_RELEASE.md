# Windows 绿色版

使用 `tools\build_windows_release.ps1` 生成发布包。构建机只需要项目自己的 `.venv` 和一次网络安装 PyInstaller；使用发布包的用户不需要安装 Python、pygame 或任何 Python 依赖。

```powershell
.\tools\build_windows_release.ps1
```

脚本默认从现有 `dist\*\easycon\publish` 查找 EasyCon 1.6.4-a。也可以明确指定：

```powershell
.\tools\build_windows_release.ps1 -EasyConPublish 'D:\EasyCon\publish'
```

输出位于 `.build\windows-release\FRLG-Auto-RNG-绿色版`，同时生成同名 ZIP。发布包是绿色文件夹，不应把 `.venv`、源码或 Python 安装包一起复制给用户。配置、日志和运行时生成的 ECS 工程会写入 `%LOCALAPPDATA%\FRLG-Auto-RNG`。

按当前源码构建的绿色版会内置 Seed 表更新器。用户在 GUI 点击“检查/更新 Seed 表”即可下载 Ten Lines 官方火红/叶绿 NX 二进制表、生成对应 EasyCon ECS 表并执行真实 1.6.4-a `format` 校验，不需要系统 Python，也不依赖外部 `Tools\update_*.py`。验证后的四个文件写入 `%LOCALAPPDATA%\FRLG-Auto-RNG\seed_tables\current`，上一版保留为 `previous`；生成运行工程时会自动覆盖两份 `lib` Seed 表。

当前使用 `onedir` 而不是单文件模式，因为 EasyCon、Tessdata、识图标签和兼容运行器体积较大，文件夹版启动更快、杀毒误报更少，也便于 EasyCon 运行时访问旁边的资源。
