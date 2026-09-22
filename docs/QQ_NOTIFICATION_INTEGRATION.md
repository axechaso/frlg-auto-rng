# QQ 通知集成准备

本轮已完成：引入独立测试工具，复用已验证的 Qt HTTP/WebSocket 客户端，并将 QQ 通知接入 PySide6 正式界面。主程序默认关闭通知；用户可从顶部“QQ 通知”入口配置机器人、绑定接收方、查看教学和规则。

## 源码与运行

- 来源线程：`01a0bc69-34ef-7701-b2c2-e8ec45831ce0`，本机 `auto-bdsp-rng/tools/qq_notify_test`。
- 源码快照及文件摘要：[SOURCE.json](../tools/qq_notify_test/SOURCE.json)。源文件未提交，不可仅按来源 HEAD 重建。
- 启动入口：[run.bat](../tools/qq_notify_test/run.bat)。完整操作说明见 [工具 README](../tools/qq_notify_test/README.md)。
- 通信实现：[client.py](../tools/qq_notify_test/client.py)，使用 `QtNetwork` 和 `QtWebSockets`，与主项目的 PySide6 6.11.2 一致。
- 测试配置：`%LOCALAPPDATA%\FRLG-Auto-RNG\QQNotifyTest\config.json`；AppSecret 和 Token 仅保留在内存。

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest tools.qq_notify_test.test_client -v
.\.venv\Scripts\python.exe -m tools.qq_notify_test.app
```

自动测试仅使用 `127.0.0.1` 上的 HTTP/WebSocket 模拟服务和虚构凭据。真实 QQ 接口只在手动操作工具时使用；用户随后已确认 FRLG 正式界面的真实连接与收发正常。

2026-09-20 本轮自动验证：Python 3.12.10 / PySide6 6.11.2，客户端 13 项离线测试和服务层 4 项离线测试全部通过；主窗口入口、设置页和教程页在 offscreen 环境创建并截图，12 张教程图全部加载。自动测试使用临时配置；真实 QQ 连接与收发由用户后续实测通过。

## 当前接入

- [notifications/qq_service.py](../notifications/qq_service.py) 保存 AppID、OpenID、规则和启用状态；AppSecret 默认只保留在内存。勾选“记住密钥”时使用 Windows DPAPI，缺少保护组件会明确提示取消勾选。
- [pyside_app/qq_notifications.py](../pyside_app/qq_notifications.py) 是原生 PySide6 设置窗口，沿用 FRLG 的深色侧栏、浅蓝灰背景、白色圆角卡片和蓝紫主按钮。包含接入设置、通知规则、发送记录和 12 步图文教学，不依赖 Qt WebEngine。
- 教学中的“打开 QQ 开放平台”按钮固定打开机器人注册页：<https://q.qq.com/#/apps>。
- [pyside_app/window.py](../pyside_app/window.py) 在运行启动、结束、启动失败和手动停止路径生成一次任务事件。退出码 0 只表示进程正常结束，通知正文会引用日志尾部，不把它直接改写成“目标命中”。通知发送失败只写入 QQ 日志和发送记录，不影响运行器结果。
- 服务层为发送实例提供有限队列、目标逐项记录、关闭取消和运行 ID 去重；任务结束只推送一次，内部重试不会逐轮推送。

## 现有可复用接口

| 接口 | 用途 |
|---|---|
| `QQClient.configure(app_id, secret)` | 配置凭据；凭据变化时清除 Token 缓存 |
| `check_credentials()` | 验证 Token 获取链路 |
| `bind("user" / "group")` | 临时连接网关，通过验证码绑定接收方 |
| `bound(kind, open_id)` | 返回已经验证的用户或群 OpenID |
| `send(targets, text, image=b"")` | 私聊／群聊发送；图片参数为 JPEG 字节 |
| `busy_changed(bool)`、`finished(bool, message)` | 更新按钮状态及通知投递结果 |
| `log(str)`、`status(str)`、`cancel()` | 日志、状态与取消 |

`QQClient` 是异步 `QObject`，应由长期存活的 Qt 对象持有，在所属 Qt 线程使用事件循环。每个实例同时只接受一个操作；后续接入需增加有限队列或明确的忙碌处理，不应直接在现有短生命周期 `Job.run()` 中创建它。

## 建议接入位置

| 现有位置 | 后续职责与约束 |
|---|---|
| `pyside_app/window.py` 的 `_process_started()` | 建立本轮运行标识及启动时的目标快照；后续切页或改参数不改变通知内容 |
| `pyside_app/window.py` 的 `_process_finished()` | 获取进程退出码、日志及普通流程上下文；退出码 0 只能表示进程正常结束 |
| `pyside_app/migration.py` 的 `_process_finished()` | 在读取孵蛋、TID、SID、SID 遍历等最终报告之后生成一次结果事件；避免和父类回调重复通知 |
| `pyside_app/window.py` 的 `_process_error()` / `stop_run()` | 区分启动失败、执行失败、用户停止；取消不得误报成功 |
| `pyside_app/results.py` 及各运行器报告 | 复用现有结果证据，区分确认命中、已结束但结果未确认、遍历耗尽、暂停与失败 |
| `app_paths.py` 的 `user_data_root()` | 正式配置放入 FRLG 用户目录；测试配置与正式配置独立 |
| `pyside_app/monitor_view.py` / `accessories.py` | 如需附图，复用已有帧；通知模块不额外打开采集卡 |
| `tools/build_windows_release.ps1` | 正式接入后补验冻结程序对 `QtNetwork` / `QtWebSockets` 的收集，以及离线运行失败处理 |

通知服务接收不可变的运行结果事件，再调用 QQ 客户端。完成、失败、取消和投递结果分别记录；通知失败不改写运行器退出码、RNG 结果或续跑进度。多阶段 TID → 御三家流程只在整条流程结束时通知，内部重试不重复发送。

首版默认关闭通知，支持一个私聊、一个群及两者同时发送。发送不自动重试；部分目标失败时保留各目标结果，避免再次发送已经成功的消息。服务实例提供排队、关闭时取消和重复事件去重。

当前工具采用用户自己的机器人凭据直连 QQ。多人共用一个机器人需要另做通知服务端和用户绑定协议，不能通过把同一 AppSecret 写进安装包来实现。独立工具阶段无需该服务端。

## 测试矩阵

| 阶段 | 用例 | 验收要求 |
|---|---|---|
| 独立工具，自动 | 私聊／群聊文字，Token 缓存及凭据变更 | 目标、中文正文和鉴权正确 |
| 独立工具，自动 | 图片分片及部分失败 | 分片顺序完整，上传地址不携带机器人 Token，文字成功不被图片失败掩盖 |
| 独立工具，自动 | 私聊／群聊验证码、READY、心跳、鉴权失败、绑定超时 | 只绑定当前验证码对应接收方，结束后关闭网关 |
| 独立工具，自动 | HTTP 取消后再次操作 | 旧请求不得触发新操作的完成信号 |
| 独立工具，自动 | GUI 按钮、配置与图片转换 | 忙碌状态正确，配置和日志不含密钥，图片可转为 JPEG |
| 独立工具，人工待验 | 真实私聊、真实群聊、两者同时发送；文字、图片、文字加图片 | 在 QQ 端逐项确认收件人与内容，记录时间和平台错误码 |
| 独立工具，人工待验 | 关闭重开、绑定超时、断网后再次尝试 | 接收方保留、Secret 需重新填写、失败后按钮恢复 |
| 主程序集成，自动 | 服务配置保存、启用条件、任务通知去重、失败投递记录 | 4 项通过；通知故障不影响运行结果 |
| 主程序集成，人工待验 | 使用假子进程及本地 QQ 服务重放完成、失败、取消、启动失败 | 已接入回调；真实 GUI 运行仍需补充回归 |
| 后续主程序集成 | TID 多阶段、内部重试、SID 遍历耗尽、退出码 0 但未确认命中 | 不将阶段完成、暂停或候选结果误报为目标命中 |
| 后续主程序集成 | 同时绑定与任务结束、连续任务、关闭窗口 | 队列和生命周期可控，无旧任务结果串到新任务 |
| 后续打包 | 源码／冻结程序、通知关闭／开启、附图可用／不可用 | Qt 模块完整，用户配置保留，缺图不影响文字通知 |

真实收发记录建议包含：用例、时间、接收目标类型、实际收到的内容类型、结果、错误码；不记录 AppSecret 或 Token。自动测试通过不等于主程序自动通知已接入，也不代替真实账号的权限与额度验证。
