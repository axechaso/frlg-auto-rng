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

当前使用 `onedir` 而不是单文件模式，因为 EasyCon、Tessdata、识图标签和兼容运行器体积较大，文件夹版启动更快、杀毒误报更少，也便于 EasyCon 运行时访问旁边的资源。
