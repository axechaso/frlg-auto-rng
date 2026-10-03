# 2026-10-03 复验原始证据

全部使用隔离目录，未操作 Switch 或真实串口。说明见[实施复验报告](../2026-10-03-six-feature-implementation.md)。

| 文件 | 被测来源 |
| --- | --- |
| `corpus-replay.json` | 用户源的 33 文件，既有物化层隔离重放，逐文件比较当前缓存；未修改源与日常缓存 |
| `assembly-samples.json` | 本机重建后实际 Device DLL 发布 / 读取 / System.Text.Json 输出，16 组样本 |
| `ci-source-samples.json` | 同锁定源码的实际 InputStateBuffer 与 SwitchCommand 枚举直接链接，16 组样本 |
| `native-protocol.json` | 生产 Python 严格解析、真实 mock HTTP / PRINT、正式 GUI 接线汇总 |
| `format-matrix.json` | 六个完整生成工程与真实固定版 format；离线确定性目标，不表示 RNG 实机命中 |
| `history-before.json` / `history-after.json` | 同工具、Qt 原生事件循环、同机 5,001 日志和 100 MiB 文件的独立性能测量 |
| `layout-{100,150,200}.json` | 两种窗口尺寸各 84 步布局检查，合计 252 步；真实 Windows 中文字体 |

## 代表截图

Qt 提示卡为独立 Tool 窗口，主窗口截图与提示卡分开保存；没有拼接或修改图片。

- 100%： [SID 主窗口](guide-sid-100.png) / [提示卡](guide-sid-100-card.png)。
- 150%： [孵蛋主窗口](guide-egg-150.png) / [提示卡](guide-egg-150-card.png)。
- 200%： [历史页主窗口](guide-history_logs-200.png) / [提示卡](guide-history_logs-200-card.png)。

这些离屏图片用于核对文本、真实控件和布局，不作为设备画面验收。
