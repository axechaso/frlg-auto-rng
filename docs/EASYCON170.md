# EasyCon 170 PC 扩展运行器

`170` 分支默认使用本地已修复单函数寄存器帧限制的运行包：

| 项目 | 固定值 |
| --- | --- |
| 版本 | `1.7.0-rc1+1cd17729fff3d0c91feef012c562473704792f78` |
| 上游基线 | `1d742f24b94464d7090f5dedf453b0864a35e8ab` |
| 本机导入源 | `D:\Codex\FRLG-OCR-FFI-Workspace\dist\pc-extension-170-20261112` |
| 工具运行目录 | `runtime_backend/easycon170-pc-extension` |
| 系统依赖 | Windows x64、.NET 10 x64 运行时 |
| 修复来源 | [EasyCon PR #89](https://github.com/EasyConNS/EasyCon/pull/89) |

PC 端通过 `PcInterpreter` 执行宽帧函数，不经过 ECX 的字节寄存器序列化。Portable／单片机编译仍保留 255 上限。无需为此拆分 BINGO、校准函数或顶层控制流，也不限制 PC 函数总数。

## 本机安装和验证

运行包不提交到 Git。仓库保留原发布清单及 SHA-256，导入时同时验证 EXE、编译器 DLL、依赖和全部七个 OCR 模型，不能只靠 EXE 名称判断版本。默认仍用原 Tesseract 模型，不自动改用 Maa OCR。

```powershell
.venv\Scripts\python.exe -m tools.import_easycon170_runtime "D:\Codex\FRLG-OCR-FFI-Workspace\dist\pc-extension-170-20261112"
.venv\Scripts\python.exe -m tools.prepare_easycon_runtime
.venv\Scripts\python.exe run_pyside6_gui.py
```

导入会先验证源，再验证临时副本；已存在的完整同版本运行包可重复检查，部分安装或被改动的目录不会被静默覆盖。高级模式只将指纹差异降为警告，缺文件、错误版本和编译失败仍阻止启动。未安装 .NET 10 时先安装运行时，再执行验证。

已有配置中已识别的 164a、旧 Actions 170、P2 路径会迁移到当前默认路径；未知自定义 EXE 保留，由预检显示错误。170 设备枚举附加的后端散列、来源 ID 和 temporary 字段会从设备名称中分离，避免临时 ID 随 CLI 进程改变而误报设备变化；原有按采集卡名称保存的标签覆盖继续匹配。重启工具并重新生成，旧生成工程不自动更新。

## 脚本与评分

普通野生、定点、孵蛋、SID、TID，以及连续流程动态生成的御三家工程都使用当前母本。170 的数组字面量要求常量，因此只在生成副本中把变量数组快照转换为常量数组加逐项赋值，保持字段顺序。转换幂等，不改变 RNG 和校准函数逻辑。

高级脚本测试将所选 ECS 及同目录 `lib`、`ImgLabel`、`data`、`Tessdata`、根目录 DLL/JSON/CSV/模型复制到本次运行目录，再转换数组语法。不替换用户参数，不改原文件；非标准位置的自定义外部资源仍须由脚本自行正确引用。预检、启动和日志使用同一份副本；源文件在预检后改变会要求重新生成。

此固定版本的 `LegacyCli` 使用 `Math.Ceiling`，与工具原有向上取整评分一致；`LegacyGui` 是截断，不能混用。正常启动命令固定传入 `--compatibility LegacyCli`。

Desktop 预检使用 `format`，此命令会完整执行 Interactive/Desktop 编译。不要用 CLI 的 `compile` 判断 PC 是否仍受 255 限制：后者目标是 Portable。

## 当前接口边界

此 170 CLI 不提供原 164a 私有运行中共享预览、按键状态和标签故障保护接口。工具不会传入无效的 `--preview-port`、输入状态或故障目录参数，也不会显示虚假的本机接口地址；标签保护开关禁用并说明原因。空闲监视、手动操作、设备标签文件覆盖和普通日志仍保留。运行中监视及标签实时修复预览会明确提示该后端不支持。

本次迁移不开发 SID 战斗练级，也没有连接单片机、打开采集卡或验证游戏命中率。设备握手、OCR 节奏及各流程实际稳定性仍需用户实测。

## 回退

保留原 164a 文件，不覆盖其运行目录。源码回退须在新进程启动前设置：

```powershell
$env:FRLG_EASYCON_BACKEND = '164a'
.venv\Scripts\python.exe -m tools.prepare_easycon_runtime
.venv\Scripts\python.exe run_pyside6_gui.py
```

移除该环境变量后恢复 170。开发时可用 `FRLG_EASYCON170_ROOT` 或 `FRLG_EASYCON170_CLI` 指定另一个同版本完整运行包；仍执行版本和依赖验证。Windows 构建脚本只收集选中后端目录，并将后端选择写入包内，164a 回退包不会在启动时误选 170。本次不制作发布包、不合并 main。

## 离线复验

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe -m tools.verify_easycon170_integration --output .tmp/170-acceptance-new
```

集成验收生成 NS1/NS2 的正式版／时间轴版野生、定点、孵蛋，SID 采集，日美 TID 普通／校准，连续流程建档／研究所／动态御三家和直接脚本测试。使用确定性目标夹具，仅验证生成、审计与 Desktop 编译，结果写入输出目录的 `report.json`。该夹具不是 RNG 命中证据。另可设 `FRLG_EASYCON_BACKEND=164a` 执行完整回退回归；CI 同时检查两个后端。
