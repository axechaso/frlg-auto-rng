# PySide6 界面初版

`pyside_preview.py` 是独立的视觉和交互原型，不替换 `run_auto_rng_gui.py`，也不会修改配置、搜索方案或启动 EasyCon。

## 当前范围

- 深色侧栏与五个可切换工作区：SID 查找、TID 乱数、野生/静态、孵蛋、运行日志。
- 公共存档信息、设备状态、方案摘要和固定底部操作区。
- 野生/静态页包含游戏与遭遇条件、六项 IV、Ten Lines 预设、筛选和范围输入。
- SID、TID、孵蛋与日志页提供接近正式功能结构的静态交互控件。
- `--screenshot` 可在测试中渲染指定页面，便于以后做视觉回归。

## 启动

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-pyside-preview.txt
.\.venv\Scripts\python.exe pyside_preview.py
```

或双击 `启动-PySide6界面预览.bat`。

指定页面并输出截图：

```powershell
.\.venv\Scripts\python.exe pyside_preview.py --page wild --screenshot .build\pyside-preview.png
```

Windows 本地视觉验收应使用上面的正常图形后端，使 Qt 载入系统中文字体。自动化测试会单独使用 `offscreen` 后端，只验证窗口能生成合法 PNG，不把该截图当作字体视觉验收结果。

## 后续接入顺序

1. 先确认窗口尺寸、颜色、侧栏和卡片密度。
2. 抽取正式 Tk 页面现有的输入模型与校验函数，不复制乱数算法。
3. 优先接入存档信息、端口/采集卡检测和日志，再接入野生/静态搜索。
4. 最后接入 SID、TID、孵蛋与脚本运行状态机，并保留 Tk 入口作为回退，直到实机验收完成。
