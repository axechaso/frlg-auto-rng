# Python 原生 EasyCon

运行主链已切换为项目内置的 Python 实现，参考 `auto-bdsp-rng` 的原生后端移植。不启动 `ezcon.exe`，也没有外部 CLI 回退。GUI、脚本测试、野生/孵蛋、SID 反查/遍历和 TID 连续流程都通过同一个原生 worker 执行 ECS。

## 运行结构

- `easycon/native/` 解析、校验和执行 ECS 主文件及同级 `lib`；支持函数、变量、数组、循环、按键、摇杆、等待、搜图与 OCR。
- `easycon/native/device.py` 通过 pyserial 实现 EasyCon 固件握手和 Switch 控制报告，停止时释放按键并断开串口。
- `capture_broker_process.py` 在独立进程中独占采集卡。脚本识别和本机 MJPEG 预览读取同一共享内存帧，避免重复打开设备。
- `easycon/native/image_labels.py` 加载 `.IL` 标签，使用 OpenCV 匹配；支持 method 14 Alpha 蒙版。`tesseract.py` 直接调用本地 Tesseract DLL。
- `run_native_easycon.py` 负责预检、设备生命周期、日志和取消；冻结包通过 `package_entry.py` 的 `native-easycon` worker 分发。

设备列表读取 DirectShow 名称与索引，不打开摄像头。执行默认采用 DirectShow（`--capture-api 700`）。帧默认使用 1920×1080；设备返回其他同宽高比分辨率时统一缩放，比例不符时报错，避免标签坐标错位。

## 源码运行

安装 `requirements-auto.txt` 后，在 GUI 中选择串口和采集设备即可。直接运行已有 ECS 工程的示例：

```powershell
.\.venv\Scripts\python.exe run_native_easycon.py `
  --project D:\path\to\main.ecs --port COM3 --video 0 `
  --log-path D:\path\to\native-easycon.log
```

可选 `--preview-port` 提供仅监听 `127.0.0.1` 的预览；`--stop-file` 指定本次运行的停止文件。GUI 和多阶段流程自动创建独立停止通道，先请求正常释放设备，超时后清理本次进程树。异常中断的外层日志/结果处理也会停止所属子进程。

旧接口中的 `ezcon_path`、部分命令行入口的 `--ezcon` 仅接受历史配置，值被忽略。`run_native_easycon.py` 本身不需要该参数。`runtime_backend/` 中历史 CLI 构建资料不参与当前执行或打包。

## 脚本和 OCR 资源

脚本包、`ImgLabel` 与游戏专用模型仍需要完整资源。串口和 ECS 原生化不替代这些数据。OCR 模型按生成工程目录、其父目录、`assets/easycon_native/Tessdata`、`local_assets/easycon118/Tessdata` 查找；DLL 来自 `assets/easycon_native/x64`。

仓库已携带 `tesseract50.dll`、`leptonica-1.82.0.dll` 和通用 `chi_sim.traineddata`。火红/叶绿脚本还使用 `frlg_battle.traineddata`、`FRLG_EN_ALL.traineddata`；从现有脚本资源包准备它们：

```powershell
.\.venv\Scripts\python.exe tools/prepare_easycon164a.py --source D:\path\to\script-package
.\.venv\Scripts\python.exe tools/prepare_easycon164a.py --check-only
```

这个工具保留历史文件名，但只准备和检查原生 OCR 资源。它不读取或执行 EXE。运行前会编译 ECS、校验标签及所需模型；模型缺失、损坏或脚本语法错误会阻止打开设备。高级模式可将已知模型的指纹差异降为警告，但不能忽略资源缺失和语法错误。

## 验证范围

自动测试覆盖串口握手与报告、ECS 语义、生成的研究所桥接脚本、标签匹配、实际 Tesseract DLL 加载、共享内存采集、HTTP 预览、机器日志续行、GUI/worker 参数以及启动中和运行中的取消。设备操作使用内存串口与模拟采集帧；这些测试不操作游戏。

独立代码审查发现并修复了三项回归：串口在打开前关闭 DTR/RTS，避免兼容板自动复位；OCR 预检实际初始化模型，损坏模型即使在高级模式也会在设备启动前被拒绝；旧 Tk 两条执行路径向原生 worker 透传高级指纹策略。审查代理已复核三项问题关闭，定向测试 38 项通过。

推送前的第二轮独立审查还补齐了数组元素赋值和持久化日志失败处理。20 份仓库自带 ECS 扩展均通过语法检查；共同区算法直接复用原 C# 检查工具中的两段 ECS 回归，验证跨 12 轮候选、排序、严格模式与重复恢复的实际执行结果。日志（含详细设备日志）或 TID 记录写入失败会使脚本失败并释放按键，后续游戏动作不会继续执行；释放和断开时持续发生日志错误也不会阻止中立报告发送和串口关闭。独立复核已确认本轮两项问题关闭。

2026-09-21 本地全量回归：`python -m pytest tests -q`，771 项通过、55 项因环境或资源条件跳过。180 份 Python 源码编译、全部后台 worker 参数入口、构建 PowerShell 语法和隔离数据目录下的 PySide6 启动截图检查通过。测试日志保存在 `.build/native-easycon-tests-final.log`，截图为 `.build/native-easycon-smoke.png`。

本次开发环境缺少完整 `local_assets` 脚本包和两份 FRLG 专用模型，因此尚未完成完整脚本语料、完整冻结发布包及 Switch 实机时序验收。发布构建会检查资源完整性。补齐资源后需要在真实设备上验证握手、按键时长、标签/OCR 和各自动乱数流程。

移植代码来源与许可证见 `easycon/native/NOTICE.md`、`easycon/native/LICENSE-GPL-3.0.txt`；OCR 组件来源见 `assets/easycon_native/LICENSE.txt`。
