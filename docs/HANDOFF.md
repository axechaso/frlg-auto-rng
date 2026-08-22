# 新设备与新对话交接文档

本文是当前火红/叶绿全自动乱数初步实现的开发快照。换设备或新建 Codex 对话时，先让新对话完整阅读本文件、根目录 `README.md` 和 `docs/INITIAL_AUTO_RNG.md`，再检查工作区实际状态。

快照日期：2026-08-21。

## 提交与 Actions 约定

每完成一轮较大的功能改动，必须先完成相应本地测试，再提交并推送到私有 `origin`，触发 GitHub Actions。零散小修可以先保留，随下一轮大改一起提交。推送前只暂存本轮相关文件，不把 `.tools/`、运行日志、生成目录或未被功能引用的研究产物混入提交。

## 最重要的迁移提醒

当前旧设备工作区：

```text
C:\Users\axenx\Documents\火叶乱数\frlg-auto-rng
```

当前发布分支：

```text
branch: main
release point: 以 origin/main 最新提交和 git log -1 为准
```

私有网络远端为 `https://github.com/axechaso/frlg-auto-rng.git`。本项目按用户约定直接把已验证的大改提交并推送到 `main` 触发 GitHub Actions，不创建 PR。具体提交号会继续前进，因此新设备必须以 `origin/main` 和 `git log -1` 为准，不能照抄旧哈希。

因此：

- 直接换设备时，复制整个项目工作区最稳妥；
- 若走 Git，克隆私有 `origin` 后直接使用最新 `main`；
- 新对话不得执行 `git reset --hard`、`git clean` 或用旧提交覆盖工作区；
- `local_assets/`、`runtime/`、`rng_logs/` 和 `.venv/` 被 Git 忽略，不会随普通提交迁移；
- 外部 1.1.8 和 EasyCon 安装包也必须单独复制或重新取得。

在新设备首先运行：

```powershell
git status --short
git branch --show-current
git log -1 --oneline
```

如果 `automation/`、`run_auto_rng_gui.py`、`tests/` 等文件不存在，说明拿到的是旧提交而不是当前工作区。

## 项目目标和当前决策

目标是让用户只进行必要信息输入，然后由工具自动完成目标搜索、方案选择、1.1.8 参数填写、预检和 EasyCon 启动。

当前已经确定的设计决策：

1. 自动执行后端先固定 EasyCon 1.6.4a，不接 1.7.0。
2. 新流程不部署 AI；OCR 由 EasyCon 1.6.4a 的本地 Tesseract 和 1.1.8 标签完成。
3. Python 负责 Ten Lines 搜索、候选排序、参数生成和启动编排。
4. 1.1.8 ECS 目前继续负责命中、OCR、IV 反查、吃糖缩小区间、跨轮投票、校准、抓捕和重试。
5. “ECS 只读能力值，IV/Seed 反查与校准状态机迁到 Python”只作为后续方案，用户已明确要求现在暂不实施。
6. 最大搜索范围使用最大 Advance，不使用“5 分钟/10 分钟”时间预设。
7. 选优规则是先取六项 IV 总和最高的结果，再取 Advance 最小的可行初始 Seed。
8. 孵蛋作为独立选项卡，不放在野生/静态类型下拉框中。
9. TID/SID 使用独立选项卡和独立 1.3.7 模板/标签包，不混入 1.1.8 主 ECS。
10. SID 查找使用独立采集模板：EasyCon 负责逐只 OCR/喂糖，Python 负责 Method 1/2/4 PID、PSV 交集和 SID 候选分析。
11. 设备检测后自动回填串口；当前值仍可用时保留，否则按 COM 数字选择最小可用端口。

## 当前运行链

```mermaid
flowchart LR
    A["GUI 输入"] --> B["Ten Lines 搜索"]
    B --> C["最高 IV 总和 / 最小 Advance"]
    C --> D["生成 1.1.8 main.ecs"]
    D --> E["版本、标签、Tessdata、format 预检"]
    E --> F["1.6.4-a CLI 兼容 runner"]
    F --> G["单片机 + 采集卡 + 本地 OCR"]
```

边界非常重要：

- `run_auto_rng_gui.py` 和 `run_auto_planner.py` 调用 `automation/`，再调用外部 `ezcon.exe`；
- `easycon/controller.py` 等旧 PyEasyCon 直连串口代码属于另一条执行链；
- 新流程不需要启动 vLLM、Ollama 或 ModelScope；
- EasyCon 1.6.4a 不含 1.7.0 的 `ir` 命令，语法预检必须使用 `ezcon format <main.ecs>`。
- 1.6.4-a GUI 对 ImgLabel 分数使用 `Math.Ceiling`，原始 `ezcon.exe run` 却用整数截断。自动启动使用固定 commit `9c86137` 构建的兼容 runner，将 CLI 取整恢复为 GUI 行为；视频后端仍为 DSHOW，英文 TID ECS 的 `HOME_BUFFER` 没有被改。

## GUI 当前状态

主入口：`run_auto_rng_gui.py`。

页面使用完整纵向滚动容器，默认窗口 1100×880，最小 900×620。右侧滚动条滚动整页；鼠标位于结果文本框时只滚动结果。

GUI 默认有四个选项卡，固定顺序为“SID 查找”“TID 乱数”“野生 / 静态”“孵蛋（测试）”。公共 EasyCon 设置中勾选“高级模式”后，才会显示第五个“脚本测试（高级）”页：

### 脚本测试（高级，默认隐藏）

- 直接选择并原地运行 `.ecs`；不搜索、不替换参数、不复制为正式 `main.ecs`，也不要求 1.1.8 完整语料指纹；
- 仍锁定原始 `ezcon.exe` 的 `1.6.4-a+9c86137` 版本、哈希和两份火叶 OCR 模型，并用它执行 `format`；
- 扫描主脚本与同目录 `lib/*.ecs` 中的直接 `@标签`，启动前确认相邻 `ImgLabel` 里存在对应 `.IL`；
- 可选“工具兼容运行器（正式工具）”或“原始 EasyCon 1.6.4-a CLI（A/B 对照）”，两者使用相同串口、采集卡、DSHOW 和命令构造；
- 输出统一保存到 `runtime/script_tests/logs/` 并在结束后回显；日志名区分 `compat/original`，同名 JSON 记录脚本 SHA-256、后端、执行文件和设备参数；
- “准备内置冲浪结束测试”只复制仓库扩展 `冲浪.IL`，等待 `冲浪 > 95` 后按一次 `X` 并停住；不会发送方向键、抓捕或存档；
- 这不是安全沙箱，所选 ECS 有完整手柄控制权限。A/B 只能证明该脚本和当次环境，不能当作正式流程实机验收。

### SID 查找

- 当前游戏和 TID、队内闪光数量、每只最多神奇糖果、识图阈值；
- 闪光数量之外的队伍行整体禁用；活动槽位可填写中文名、英文名或全国图鉴编号，由 Python 统一解析成编号；每行还必须填写初始等级、定点/野生来源、野生相遇地点，以及 HP、攻击、防御、特攻、特防、速度六列努力值；摘要页名称和等级 OCR 已从正式判定移除；
- “准备 SID 查找”生成并预检独立采集工程；“开始运行”逐槽采集，PSV 唯一后提前结束；
- 报告回显到主界面，并保存到 `runtime/sid_reverse/`；
- 只覆盖第三世代 Method 1/2/4，孵蛋来源及其他 PID 生成方式暂不支持。

### 野生 / 静态

- 游戏：火红/叶绿；主机：Switch 1/2；TID/SID；
- 类型下拉框只有野生和静态；
- 遭遇方式、地点和目标宝可梦联动；
- 六项 IV 分别填写最低/最高值；
- 不限、6V、0A、0S、0A0S 预设和单项重置；
- 运行模式（筛选搜索/指定 Seed/帧数）、最小/最大 Advance；
- 闪光、性格、性别、特性、觉醒力量、Seed 模式；筛选项在 GUI 中显示中文，提交搜索时映射回 Ten Lines 内部值；
- “特性：不限”必须映射为 Ten Lines 的 `Any`；底层 `resolve_ability_idx()` 也保留中文“不限”的防御性兼容；
- 自动抓捕、麻痹、点到为止选项。

Ten Lines 预设是精确 IV，不是“其余任意”：

```text
6V    = 31/31/31/31/31/31
0A    = 31/0/31/31/31/31
0S    = 31/31/31/31/31/0
0A0S  = 31/0/31/31/31/0
```

### 孵蛋（测试）

- 独立显示游戏、主机、Seed 模式和蛋种；蛋种为可编辑自动补全框，接受中文名、英文名、完整下拉显示名或全国图鉴编号；
- 目标 Seed、Held/生成帧、Pickup/领取帧；
- 双亲相性 20/50/70；
- 双亲性别和六项 IV；
- 启动准备可选择“完整准备”或“从已完成254步准备开始”；后者只跳过一次性走位、设置检查和存档，后续 HOME_BUFFER 与全部校准流程不变；
- 必须勾选实验性时间轴确认。

孵蛋页不负责搜索蛋目标。用户必须先从 Ten Lines Egg 页取得同一初始 Seed 下的 Held 和 Pickup。Pickup 至少比 Held 晚 1800 帧。

孵蛋两次野生 Seed 反查都选择刚捕获的队伍末位，从队首向上按 2 次；正式轮的蛋先进入第 5 位，复核野生后进入第 6 位，所以之后蛋个体反查固定选择第 5 位并按 3 次。首次打开能力页与神奇糖果选择必须共用这一目标身份规则，不能再只根据槽号推断按键次数。

生成的运行副本将 `$野生PID尝试上限` 覆盖为 200（导入模板仍保持其已审计的 1000 指纹）。这是实机折中：已出现过超过 100 次的长尾 PID，故不能回退为 100；又避免 1000 在完整 Wild1/Wild2/Wild4、宽帧窗反查中造成过长无输出扫描。不要删减三种野生算法来换速度。

池塘 Seed 预校准与领取后复核的实机日志已证明冲浪流程存在转场竞态。实机画面确认过冲浪完成前第一次 `X` 被吞，后续 `DOWN` 因主菜单未打开而让人物在地图向下移动一格。运行时覆盖把冲浪确认的第三次 `A` 前等待从 800 ms 增至 2000 ms；第三次 `A` 后只循环采样仓库扩展标签 `冲浪`，分数 `> 95` 表示冲浪操作已经结束，此时立即停止识图并按一次 `X`，再沿用原版 `WAIT 500 → DOWN`。最多 10 秒仍未命中时禁止按 `X` 并返回失败。这里不再额外读取 `三代菜单栏`，也绝不能使用御三家流程的 `火红BAG`。使用甜甜香气后仍要求名称 OCR 前命中 `野生出现 > 90` 或 `抓捕就绪 > 95`，最多 4 次只等待重采样仍不成立就返回失败，让外层重启。后续排查先看 `孵蛋池塘冲浪检测|...|冲浪=...`，再看 `孵蛋池塘战斗检测|...`。

2026-08-22 12:24 的实机日志显示前三轮 Seed 预校准正常，第 4 轮已经完成生成和领取，但池塘 `冲浪` 标签 20 次均为 73。池塘函数返回 `-1` 后，上层确实调用了 `孵蛋流程_重开下一轮`，HOME_BUFFER 也重新命中 96；随后仍退出的原因是该分支返回 `0`，而总控把 `0` 当作不可恢复终止。生成时的瞬时重试覆盖现把生成/领取/复核抓捕动作失败、领取后野生 Seed 反查失败和孵化动作失败统一改为重启后返回 `2`；只有 HOME_BUFFER、时间轴计算或明确数据错误继续返回 `0`。不要再把“画面已经重启”当成外层一定会 `CONTINUE`，必须检查阶段函数最终返回值。

孵蛋 Seed-only 校正也已换成正式版 `计算Seed锁定众数修正()`：初始累计索引仍取 NS1/NS2 预校准值；大偏差按正式限幅靠近，可信 `±1` 直接走相邻索引，两个相邻请求命中方向反转时切入毫秒中点，再按最近 5 轮 3 票二分。只重算 `$孵蛋Seed等待MS`，不调用通用帧轴校准，也不修改 Held/Pickup。生成后的日志应出现 `【孵蛋Seed校准】`，旧的 `孵蛋Seed-only校正: ...新等待...` 不应再出现。

2026-08-20 后续实机已走到领取后 Seed 复核命中，但孵化入口把 `UP 200` 作用到了 Wooper 的 `SUMMARY/SWITCH/ITEM/CANCEL` 操作菜单。原因不是第 5/6 槽选择次数，而是旧 `孵蛋测试_执行骑车孵化()` 从能力页退出时只发送 3 次 `B`，且前两次只等待 500 ms。运行时覆盖现改为 5 次 `B + WAIT 1500` 后才允许 `UP 200`，并输出 `孵化退出进度: n/5` 与每 10 圈的 `孵化骑车进度`。不得通过修改野生末位 2 次 `UP` 或蛋第 5 位 3 次 `UP` 来处理此问题。

### TID 乱数

- 英文/日文 ROM、乱数/穷举、Switch 1/2、主角性别和名称；
- 目标 TID/SID 与三种 SID 处理模式；
- OP/F1/F2 中心帧、搜索半径、穷举起点和范围；
- 固定延迟、游戏设置、去噪与特殊号码判定；
- 英文连续流程开关，以及游戏版本、御三家、ADV 上下限和 SID ADV 重试半径；御三家 Seed 时间直接使用 Ten Lines 对应设置的 Seed 表，不接受人为时间下限；
- 独立脚本包路径，默认是 `%USERPROFILE%\Downloads\自定义TID SID 御三家乱数多功能包1.3`。

适配器位于 `automation/tid_rng137.py`。它锁定英文/日文 1.3.7 脚本指纹和 328 个标签。日文原脚本 `FOR $InputLen` 在 1.6.4-a 会报三次只读 `_tmpL$0`；生成副本会按 ECS 约束改为先算有效末索引再使用显式索引 `FOR`。该修正不改 Seed/帧轴，不改用户原包。

连续流程采用分阶段编排，不把英文、日文和旧御三家模块复制到一个 ECS：

1. 根据 ROM 语言生成一份原版 1.3.7 ID 脚本，只增加 `TIDFLOW|ID|...` 成功标记；
2. 使用用户提供集合样本中已经实测的研究所路线，保存到所选御三家球前；
3. 由共享 Python 搜索器从 ADV 1500 起找最早可达闪光 Method 1 御三家，并把 Seed、ADV、图鉴编号和 Seed 模式写入现有 1.1.8 `Starter` 工程；
4. 第三阶段直接复用 1.1.8 的御三家领取、能力读取、反查和校准；输出“已识别到出闪，脚本停止”即完成；
5. 若 1.1.8 精确命中目标 Seed/帧后输出“已命中目标，脚本停止”但没有出闪，编排器判定 SID 未命中，并按当前 `$SID_ADV修正`、`+1`、`-1`、`+2`、`-2` 的顺序重新执行全部三段。

实现位于 `automation/tid_starter_flow.py`、`rng/starter_sid_verification.py` 和 `run_tid_starter_flow.py`。GUI 的 TID 页会输出 `01_id`、`02_lab_bridge`、`03_starter_118` 和 `flow_plan.json`，对三份主脚本做 1.6.4-a 预检，并由 Python 按成功标记顺序启动。每个 SID ADV 修正都有独立的 ID 主脚本，共用同一套已审计标签。现有 1.1.8 的 Seed 表/OCR 只审计英文版，因此日文 1.3.7 仍可单独运行，但日文连续流程会被明确拒绝。集合样本中的旧 1.2.3 御三家 OP/F12 控制器没有导入。当前尚缺 Switch 实机三阶段与 SID 重试验收。

## 代码导航

| 文件 | 作用 |
|---|---|
| `run_auto_rng_gui.py` | 四个正式选项卡、默认隐藏的高级脚本测试页、输入校验、后台搜索/采集、方案展示、预检和启动/停止 |
| `run_sid_reverse_capture.py` | SID 逐槽采集编排、提前收敛和报告落盘 |
| `run_sid_reverse.py` | SID 采集日志分析与文本报告 |
| `run_tid_starter_flow.py` | 按成功标记串行运行 TID、研究所桥接、1.1.8 御三家，并自动处理 SID ADV 重试 |
| `run_auto_planner.py` | 普通野生/静态命令行计划器；默认只生成，`--run` 才启动 |
| `automation/planner.py` | `AutoSearchRequest`、分层搜索、最高 IV 总和、同分最小 Advance |
| `automation/seed_modes.py` | 1.1.8 Seed 模式 0–9 与 Ten Lines 游戏设置映射 |
| `automation/static_targets.py` | 静态类别和版本限定白名单 |
| `automation/support.py` | 路线启动边界；狩猎区/碎岩等保守阻止 |
| `automation/easycon118.py` | 1.1.8 参数替换、指纹、EasyCon 预检、设备枚举和运行命令 |
| `automation/script_test.py` | 任意 ECS 原地预检、直接标签检查、原始/兼容运行器 A/B 与内置冲浪结束测试工程 |
| `automation/sid_reverse118.py` | SID 采集请求校验、模板参数替换与工程生成 |
| `automation/tid_rng137.py` | TID/SID 1.3.7 模板/标签锁定、参数替换、日版 1.6.4-a 兼容和预检 |
| `automation/tid_starter_flow.py` | TID/SID 到御三家的分阶段计划、ID 重试脚本、研究所桥接和 1.1.8 Starter 工程 |
| `rng/tenlines_utils.py` | Ten Lines 搜索、IV 分层、资源读取和 C++ 接口 |
| `rng/sid_reverse.py` | Method 1/2/4 PID、PSV 与 SID 候选恢复 |
| `rng/sid_reverse_workflow.py` | SIDREV 日志解析、IV 区间和多只宝可梦交集 |
| `rng/starter_sid_verification.py` | ADV 1500 起的最早闪光御三家搜索及目标命中后的 SID 判定 |
| `easycon/label_matcher.py` | 方法 1/5/14 的统一标签匹配兼容层 |
| `tools/import_easycon118.py` | 从外部 1.1.8 包导入已审计快照 |
| `tools/import_tid_rng137.py` | 从外部多功能包导入已审计的 TID/SID 1.3.7 日英模板与标签 |
| `tools/prepare_easycon164a.py` | 锁定 ezcon 版本/哈希并安装两份火叶 Tessdata |
| `tools/build_easycon164a_compat_runner.ps1` | 从固定 1.6.4-a commit 重建 GUI 识图取整兼容 runner |
| `runtime_backend/README.md` | 兼容 runner 的原因、边界和校验方式 |
| `tools/audit_easycon118_labels.py` | 标签审计工具 |
| `tests/` | 计划、GUI 输入、孵蛋、标签和 1.6.4a 后端测试 |

本机运行目录：

```text
local_assets/easycon118/   经审计的外部脚本快照
local_assets/tid_rng137/   经审计的 TID/SID 1.3.7 快照
runtime/easycon118/        最近一次生成的 main.ecs、lib、ImgLabel、plan.json
runtime/sid_reverse/       SID 采集工程、日志和结果报告
runtime/tid_starter_flow/  TID、研究所、1.1.8 御三家三阶段工程和连续流程日志
runtime/script_tests/      高级模式内置/自选测试工程和独立运行日志
rng_logs/plans/            每次普通或孵蛋生成的 JSON 记录
runtime/launcher.log        BAT 启动日志
```

这些目录都不能被当作源文件修改入口。模板应从外部 1.1.8 包重新审计导入，生成工程由 Python 重新产生。

## 固定版本与资产指纹

### EasyCon 1.6.4a

```text
version: 1.6.4-a+9c86137c7e63bff842175470895727a5fa9bab52
ezcon.exe SHA-256: 559b81c234d2548c439926a88f5355ccac0958b8a191c1ecca48b2c7c71c1260
default path: %USERPROFILE%\Downloads\伊机控-EasyCon-v1.6.4alpha测试版-260518\publish\ezcon.exe
```

自动执行兼容 runner 同样来自 commit `9c86137c7e63bff842175470895727a5fa9bab52`，功能补丁标识为 `cli-latest-frame-ceiling-ocr-onedir-v4`。入口为 `EasyCon2.CLI-ocr-v4.exe`，当前入口 SHA-256 为 `258b9a6ffeb6fe0eedefb38f91210e48943c1205ce967c2f5d6b72124c4f8eb1`。它让 ImgLabel 与本地 OCR 共用持续采集的最新帧，并使用 GUI 的向上取整。必须保留完整自包含文件夹；Tesseract 5.2 在单文件发布中无法取得原生库目录。运行文件因体积较大被 Git 忽略，只用 Git 迁移时须运行 `tools\build_easycon164a_compat_runner.ps1` 重建。

### 1.1.8 正式/孵蛋脚本

```text
主 ECS + lib 文件数: 33
原包兼容输入 SHA-256: 7d5e13e4391d5bcc9045044544f409919a6f95c602e2ad0308313470ce23e625
合并 1.6.4-a 修正后的固定 SHA-256: aea14e79615bfda89e1f7428014adc2dcc848005bd7ebad0bd170eac67703aef
```

安装器只接受上述原包输入或已经合并修正的固定语料；原包会在复制到 `local_assets/easycon118/` 后自动升级，再按新指纹复核。两份入口和共享 `lib` 因而可以直接运行，不再依赖 GUI 临时覆盖。不要把曾经的旧快照指纹 `db50e6...` 或有 `$调试日志输出` 编译问题的其他快照直接替换进来。

### 标签

```text
总数: 1150
方法 1: 17
方法 3: 1
方法 5: 777
方法 11: 1
方法 14: 354
标签语料 SHA-256: 00d2fbfa9a3638f3cea64553e94b777ed8c5c63f813125617b50aaeed7c9d10e
```

SID 入口、`闪公图标.IL` 和孵蛋池塘用的 `冲浪.IL` 作为仓库内置扩展保存在 `assets/easycon118_extensions/`。导入器会把两份标签以规范的一行格式覆盖到快照，再校验 1150 标签的新指纹，因此旧包不要求预先带有这些扩展。SID 六项能力合法范围分别代入各项努力值，不能回退成 EV=0。Python 根据图鉴编号和火红/叶绿版本把完整第三世代六项种族值与性别阈值写入 ECS；不能调用 1.1.8 原有的不完整目标表。用户手填每只初始等级，后续等级按成功喂糖次数 `+1`。

方法 14 必须保留原 Alpha 通道作为 `TM_SQDIFF_NORMED` 的 mask。

### 火叶 OCR 模型

```text
frlg_battle.traineddata:
7abcaef4936727b33717656b38fd5b5027823e1cafec21abb06cc8ef1f7ff758

FRLG_EN_ALL.traineddata:
3272f23a6f259518813025d89be77d706574ccdf163132ccf6f5be15ca19cfa0
```

EasyCon 1.6.4a 的 OCR 是本地 Tesseract，不依赖外部 AI 服务。原始 1.6.4a 压缩包只有通用数据时，必须由安装器补齐以上两份模型。

## 新设备安装核对

1. 安装 Windows x64 Python 3.12。
2. 确认 `rng/src/pybind/calibration_bind.cp312-win_amd64.pyd` 存在。
3. 把 1.1.8 包放到 `%USERPROFILE%\Downloads\NS火叶全自动一键乱数1.1.8`。
4. 把 EasyCon 1.6.4a 放到默认目录，或后续显式调整准备脚本和 GUI 路径。
5. 运行 `安装-自动乱数首版.bat`。
6. 运行 `启动-自动乱数首版.bat`。
7. 在 GUI 点击“检测端口/采集卡”，不要照搬旧设备的 COM 号和采集卡序号。

若安装器已经创建旧的错误 `.venv`，应先人工确认没有需要保留的内容，再删除 `.venv` 并用 64 位 Python 3.12 重装；不要由新对话擅自删除用户目录。

## 验证命令和当前基线

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m py_compile run_auto_rng_gui.py
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe tools\prepare_easycon164a.py --check-only
```

2026-08-22 的代码基线：项目 `.venv` 运行 157 项单元测试全部通过；导入快照的正式/时间轴入口、下载目录的正式/时间轴入口和当前生成的孵蛋脚本均通过真实 EasyCon 1.6.4-a `format`。下载包共有 23 个 `Tools/check_*.py`，当前 20 个通过；以下 3 个是外部下载包对旧函数/文案的已知陈旧断言：`check_egg_timeline_mode.py`、`check_seed_mode_calibration.py`、`check_seed_success_hold.py`。换设备复测必须同时报告“20/23”和这三个文件名，不能简写成全部通过。本轮把用户制作的 `冲浪.IL`（规范文件 SHA-256 `948b8a57ccabfb86d5c358208d7d2a944a8133a56a58ba24d6ce5fafb0d04fe9`）纳入仓库扩展和 1150 标签审计语料；孵蛋池塘流程只循环读取这个标签，首次 `> 95` 后立即停止识图、按一次 `X` 并沿用原版 `WAIT 500 → DOWN`，不再读取 `三代菜单栏` 或御三家用的 `火红BAG`。瞬时动作失败在完成重启后返回 `2` 进入下一轮，不再错误返回 `0` 终止总控。以上修正已经固化到导入后的两份 1.1.8 入口和共享库，生成器仅做幂等配置；当前下载目录脚本也已同步。这只是代码与语法验证，仍需 Switch 实机复测。SID 第一只闪光雄性大比鸟曾完成两轮连续实机采集，均得到 Lv46、Jolly、`133/120/83/72/73/144`；此前还完成四个正式页签顺序、默认隐藏高级页、SID 输入/运行链、御三家目标搜索和英文三阶段连续流程生成/预检的静态验证。确认：

- 页签顺序固定为 SID 查找、TID 乱数、野生/静态、孵蛋；
- 设备枚举会自动回填可用串口；
- 普通类型下拉框不再包含孵蛋；
- 孵蛋参数可收集成 `EggRunRequest`；
- 900×620 窗口可滚动到页面底部；
- “隐藏属性”文案已经改为“觉醒力量”。
- TID/SID 日英参数可收集，日文生成副本可通过真实 1.6.4-a `format`。
- TID 连续流程已接入 GUI 生成和启动链；英文 ID 重试脚本、研究所桥接和现有 1.1.8 Starter 工程由 `run_tid_starter_flow.py` 按成功标记串行执行，SID 偏离时按计划重建存档。三阶段仍未完成 Switch 实机验收，日文连续流程也尚未开放。

本机曾验证 1.6.4a 可以枚举串口和视频设备，并可用 `format` 解析当前 ECS。换设备后设备编号必然可能变化，必须重新检测。

## 已知边界和禁止误报

| 功能 | 当前状态 |
|---|---|
| 普通野生路线 | 搜索/生成/启动链已接通；仍需按地点实机验收 |
| 静态目标 | 7 类、每版 27 个 GUI 目标；已接通但仍需实机验收 |
| 普通碎岩 | 1.1.8 明确未完成，只搜索，不启动 |
| 狩猎区 | 中央/东/北/西区草丛及三种钓竿路线已实现并开放生成、启动；冲浪/碎岩仍按脚本支持范围限制 |
| 漫游三圣兽 | 截断 IV bug 与存档御三家约束未实现，不开放 |
| 孵蛋 | 同 Seed ECS 代码/语法测试通过，尚未实机验收 |
| EasyCon 1.7.0 | 不支持；接口/标签差异待以后重新核对 |
| Python 接管 IV/Seed 反查 | 已调研，用户要求暂缓 |
| AI/VLM | 新流程不需要；旧 PyEasyCon 链仍可能需要 |

不要把“单元测试通过”“ECS format 通过”描述为“实机全自动稳定完成”。

## 建议的下一步

按风险从低到高：

1. 在新设备重新跑安装、157 项测试、EasyCon `--check-only` 和设备枚举。
2. 用不会影响存档的短 ECS 验证单片机控制、停止和重新连接。
3. 选一个普通野生基线路线做单轮命中、OCR、反查和校准日志验收。
4. 再做重复循环、抓捕和长时间稳定性。
5. 单独验收孵蛋前置条件、Held/Pickup 两次命中和孵化反查。
6. 最后才考虑开放狩猎区或迁移 Python 反查状态机。

如果继续改善软件而不接硬件，优先事项可以是：增加 GUI 自动化测试、把外部包路径做成持久配置、完善错误日志与恢复，以及为实机验收建立黄金日志/截图集。

## 可直接粘贴到新对话的提示

```text
请接手这个火红/叶绿全自动乱数项目。先完整阅读 README.md、docs/HANDOFF.md 和 docs/INITIAL_AUTO_RNG.md，然后运行 git status --short，确认不要覆盖或清理现有未提交改动。

当前主入口是 run_auto_rng_gui.py：GUI 依次有“SID 查找”“TID 乱数”“野生 / 静态”“孵蛋（测试）”四个正式选项卡，整页可滚动。公共设置勾选高级模式后才显示“脚本测试（高级）”：它可把同一 ECS 原地交给正式兼容 runner 或原始 1.6.4-a CLI 做 A/B，不经过参数生成。SID 页逐只采集闪光宝可梦并由 Python 反查；TID 页使用锁定的英文/日文 1.3.7 脚本和独立标签包。普通流程由 Ten Lines 搜索，按最高 IV 总和、再按最小 Advance 选择方案，生成 1.1.8 ECS 后交给固定 EasyCon 1.6.4a。本流程不部署 AI。孵蛋只接收 Ten Lines Egg 页已经得到的同 Seed、Held 和 Pickup，尚未实机验收。

EasyCon 必须锁定 1.6.4-a+9c86137...，预检使用 ezcon format，不要改成 1.7.0 的 ir。狩猎区、碎岩、漫游兽和孵蛋不能宣称已实机完成。IV/Seed 反查迁到 Python 是以后方案，当前不要实施。

先运行：
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m py_compile run_auto_rng_gui.py
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe tools\prepare_easycon164a.py --check-only

测试基线是 157 项。下载包 ECS Tools 为 20/23；三个已知陈旧失败固定是 check_egg_timeline_mode.py、check_seed_mode_calibration.py、check_seed_success_hold.py。1.1.8 原始审计语料会在导入本地快照时自动合并 1.6.4-a 修正，固定指纹见上文；不要绕过导入器混用未知脚本。完成环境核对后，请根据我接下来的要求继续，不要自行扩大到实机运行或修改 TID/EasyCon 原包。
```
