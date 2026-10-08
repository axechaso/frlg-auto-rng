# Windows 绿色版

使用 `tools\build_windows_release.ps1` 生成发布包。构建机使用项目自己的 `.venv`，脚本锁定安装 PyInstaller 6.15.0、PySide6 6.11.2 与 truststore 0.10.4；用户不需要安装 Python。当前发布合同为 `0.9.5 / 2026100701`，正式界面仅为 PySide6，不含旧 Tk。发布资源使用已审计的两个 2.0 入口、31 个 ECS 库、Seed 表状态文件、1155 个共同标签及保留的 TID r5；不得为追求“全同步”把 r4 覆盖回去。

```powershell
.\tools\build_windows_release.ps1 `
  -BuildTag pyside6-0-9-5-20261007-r4 `
  -EasyConPublish 'D:\Download\伊机控-EasyCon-v1.6.4alpha测试版-260518\publish' `
  -LocalAssets .\local_assets `
  -NotesFile .\docs\releases\v0.9.5.md
```

脚本默认从现有 `dist\*\easycon\publish` 查找 EasyCon 1.6.4-a。也可以明确指定：

```powershell
.\tools\build_windows_release.ps1 -EasyConPublish 'D:\EasyCon\publish'
```

输出位于 `.build\windows-release-pyside6-0-9-5-20261007-r4\FRLG-Auto-RNG-0.9.5-windows-x64`，同时生成同名 ZIP、`update-manifest.json`、`.sha256`、`incremental-release-assets` 和 `gitee-release-assets`。增量资源生成后逐文件与完整 ZIP 核对，末尾执行冻结版本探针和隔离数据目录下的 PySide6 截图冒烟；截图模式停止自动更新计时器并等待窗口安全关闭，不强制丢弃仍在运行的线程，正常启动仍自动检查更新。只收录当前 `runtime_backend/easycon164a-cli-gui-rounding-selfcontained`，不带入旁边的旧备份目录，也不删除工作区备份。不要把 `.venv`、源码或 Python 安装包一起复制给用户。配置、日志和生成的 ECS 工程写入 `%LOCALAPPDATA%\FRLG-Auto-RNG`。

按当前源码构建的绿色版会内置 Seed 表更新器。用户在 GUI 点击“检查/更新 Seed 表”即可下载 Ten Lines 官方火红/叶绿 NX 二进制表、生成对应 EasyCon ECS 表并执行真实 1.6.4-a `format` 校验，不需要系统 Python，也不依赖外部 `Tools\update_*.py`。验证后的四个文件写入 `%LOCALAPPDATA%\FRLG-Auto-RNG\seed_tables\current`，上一版保留为 `previous`；生成运行工程时会自动覆盖两份 `lib` Seed 表。

当前使用 `onedir` 而不是单文件模式，因为 EasyCon、Tessdata、识图标签和兼容运行器体积较大，文件夹版启动更快、杀毒误报更少，也便于 EasyCon 运行时访问旁边的资源。

## 母本同步时的必查项

每次同步母本、打包发布前，必须对照母本的运行前要求，检查工具启动确认弹窗、页面引导和说明是否同步。工具文案是独立代码，更新母本不会自动更新它。

- 普通队伍要求当前为“队伍至少留有一个空位。”；道具乱数按设置预留空位，波克比保留蛋与Seed复核的特殊要求，不能统一覆盖特殊分支。
- 反查捕捉当前要求为“球袋第一格放反查用球（大师球最佳）”，不是必须大师球；同时核对出闪后抓捕球、神奇糖果、血药等位置。
- 运行 `tests.test_pyside_backend` 的相关回归，并在待发布包中实际生成方案、打开启动确认框，检查要求和突出显示的信息；不启动真实脚本即可验收文案。若母本要求再次变化，同步调整文案、测试和本清单。
- 预校准写回须覆盖配置目标出闪提前停止、能力页目标出闪、完整反查命中、无标记、非法/不完整标记，运行 `tests.test_precalibration` 与 Qt 结束回调测试。新生成普通野生/定点的目标出闪不需抓捕反查即可保存当轮修正；非目标闪光、失败、手动停止不保存，旧工程缺标记不报格式错误。不能绕过配置目标、上下文、帧作用域校验，也不能以成功参数标记代替 SID 身份证明。实际母本/标签不改，使用固定 164a 对生成工程执行完整编译和 `tools/EasyCon164aPrecalibrationCheck` 纯函数检查（输出新报告路径及 main.ecs；无硬件）。

## 程序增量更新

绿色版包内包含 `FRLG-Auto-RNG-Updater.exe`。启动后会在后台检查公开仓库的最新稳定 Release，每 24 小时最多自动检查一次；“检查程序更新”按钮可手动触发。程序更新源可选“自动（GitHub 优先）”“GitHub”或“Gitee”。自动模式下，GitHub 检查成功时不访问 Gitee，只有 GitHub 检查失败才读取 Gitee 最新正式 Release；手动选择 GitHub 或 Gitee 时只使用指定源，不跨源回退。

2026-10-08后的新构建优先读取 `incremental-packs.json`，同时兼容历史 `incremental-manifest.json`：按文件大小和 SHA-256 比对当前安装目录，显示预计按需下载量、相关整份压缩包回退上限及可复用文件数，用户确认后才下载。未变化的文件直接复制到独立暂存目录；缺失、损坏、新增或变化的文件由所需数据块重建。新目录只包含清单中的文件，因此新版删除的旧文件不会残留。无须指定某个旧版本作为补丁基线。已发布v0.9.5资产不覆盖，合并格式从下一次新版本发布启用。

大于等于1 MiB的文件仍独立分块；新构建把小型文本/脚本/IL标签与小型二进制运行库分开，各按路径分16个稳定桶。每块原始数据最多16 MiB，压缩后最多约16.1 MiB；发布时分门别类放入少量不超过90 MiB的ZIP。支持HTTP Range时只读取所需块；不支持时只下载相关ZIP，并明确更新预计量及进度。变化块可能带有同组未变化的小文件，因此不是逐字节二进制差分。校验后的小块缓存到 `updates/bundles`，整ZIP缓存到 `updates/archives`；重试复用已完成内容。旧缓存中符合新清单摘要的块仍可复用，旧格式纯转换不改变块摘要；详细合同见 [合并增量更新](PACKED_UPDATES.md)。

增量清单必须与完整更新清单的版本、版本码、完整 ZIP 摘要和解压大小一致；每包校验压缩大小与 SHA-256，解压有大小上限，每个组装后的文件再次校验大小与 SHA-256。自动模式的 GitHub → Gitee 下载回退还要求两边的增量清单完全一致。手动模式仍不跨源。清单缺包或校验失败时报告错误，不悄悄改成全量下载。

旧更新器不会读取新的 `incremental-packs.json`，因此能使用原完整ZIP/Gitee90 MiB分卷先升级一次。新版遇到未提供增量清单的历史Release时，会明确告知需下载完整包。原schema 1整包清单字段保持不变，完整包和旧分卷继续发布。新清单缺包或损坏时不暗中退回旧格式；两源须格式、清单和压缩包完全一致。增量更新不会修复Gitee API自身返回的403。

程序更新始终安装完整的新版本，不提供运行中独立切换标签、Seed 表或脚本的热更新。标签可通过“标签”页导入设备专用覆盖，Seed 表继续使用独立的 Seed 表更新器。

安装会在主程序退出后由独立更新器完成目录交换；交换失败或新版启动确认超时会自动恢复旧目录。`%LOCALAPPDATA%\FRLG-Auto-RNG` 下的配置、日志、TID/SID 进度、Seed 表和设备标签覆盖不参与替换。EasyCon 或搜索流程运行时禁止安装。

现有 `0.2.2` 绿色包可通过原有整包更新器直接升级到 `0.9`，因为主程序、独立更新器、schema 1 清单和健康探针合同保持不变。`0.2.1` 或更早版本若受旧证书链问题影响，应手工安装 `0.2.2` 或 `0.9`，不得关闭 TLS 验证。源码运行模式不会联网自更新。

## 已发布 `0.9.5` 与下一次发布

下面是0.9.5的历史发布命令，原tag/线上资产保持不变。下一次发布先提高 `app_version.py` 中的版本号和版本码、准备对应说明，使用新构建目录；新生成的增量资产为少量ZIP格式，不重复发布已有v0.9.5。

确认 `main` 已推送且 GitHub Actions 成功后运行：

```powershell
.\tools\publish_windows_release.ps1 `
  -BuildRoot .build\windows-release-pyside6-0-9-5-20261007-r4 `
  -Tag v0.9.5 `
  -Title "FRLG Auto RNG 0.9.5 PySide6版" `
  -NotesFile .\docs\releases\v0.9.5.md
```

脚本先验证完整包与所有增量资源内容一致，再创建草稿 Release，上传完整 ZIP、`update-manifest.json`、SHA 文件及 `incremental-release-assets` 内清单引用的全部资源，并回读资产名称和增量包大小。校验未完成时草稿保持不公开，不会覆盖已有 tag。

### 手工上传 Gitee 更新源

每次执行 `build_windows_release.ps1` 都会在构建根目录生成 `gitee-release-assets`。该目录只包含需要手工上传到 Gitee Release 的文件：

```text
gitee-update-manifest.json
incremental-packs.json
update-pack-<SHA256>.zip
...
FRLG-Auto-RNG-<版本>-windows-x64.zip.001
FRLG-Auto-RNG-<版本>-windows-x64.zip.002
...
```

兼容旧客户端的完整ZIP默认每卷90 MiB；合并清单和ZIP与GitHub完全相同。内部独立 `.bin` 不再作为附件上传。Gitee须使用与GitHub相同的新版本标签，并上传新构建 `gitee-release-assets` 内全部文件原名；不要漏传、改名或只传旧分卷。无需再上传完整ZIP、GitHub整包清单或SHA文件。用户负责网页上传，脚本不登录/发布Gitee。旧v0.9.5目录仍有113个旧格式资产，不能与下一版新目录混用。
