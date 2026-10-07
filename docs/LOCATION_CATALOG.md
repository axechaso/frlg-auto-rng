# 遭遇地点命名、排序与搜索

更新日期：2026-10-07。仅调整地点目录和 PySide6 输入，不改变 Seed、PID、IV、奇偶或校准算法，不同步或改写用户的 ECS 母本与标签。

## 统一名称

本工具的 105 组中英文地点名逐项对照 Ten Lines 使用的翻译资源。固定参考为 [Ten Lines resources.ts](https://github.com/lincoln-lm/ten-lines/blob/fbd089b55e9a2a894cfa31d7da39f39febeb196a/src/tenLines/resources.ts) 及其 PokeFinder 子模块的 [英文地点](https://github.com/Admiral-Fish/PokeFinder/blob/fddaee74e6e3a2cfebc59c7624ffca2f6d1c6b4b/Source/Core/Resources/i18n/en/frlg_en.txt)、[中文地点](https://github.com/Admiral-Fish/PokeFinder/blob/fddaee74e6e3a2cfebc59c7624ffca2f6d1c6b4b/Source/Core/Resources/i18n/zh/frlg_zh.txt)。回归参考固定在 `tests/fixtures/tenlines-frlg-locations.json`，测试不依赖网络。

不归之穴不再逐个列出房间编号，而是区分两张不同的遭遇表：

| 显示名称 | 搜索内部名称 | 原始地图 |
| --- | --- | --- |
| 不归之穴 | Five Island Lost Cave | Room1–Room10 |
| 不归之穴（有物品的房间） | Five Island Lost Cave Item Room | Room11–Room14 |

旧中文“房间N”和英文“Lost Cave Room N”**不兼容**：不加入别名、自动转换或补全匹配。用户在输入框中填写旧名称时必须重新选择规范地点；不会偷偷改成首项或沿用先前地点。原始地图常量仍按上表归入实际遭遇表，这不是旧用户输入的兼容层。已有生成工程、日志和外部脚本保持不变，升级后重新生成方案。

检查时还发现七个石室被合并到“阿斯卡纳遗迹”。现在分别显示伊莱斯石室、那藏石室、由格石室、阿利波卡石室、科斗石室、阿努泽石室和澳利弗石室；“阿斯卡纳遗迹”本身仍是独立的水域地点。其他原有的 98 组规范中英文名称均与固定参考一致。移除没有对应独立目录项的道路21南/北显示名，使用“21号道路”。

## 遭遇目录一致性

- 火红与叶绿各有 105 个地点、296 个“地点＋遇敌方式”条目。草丛86、冲浪49、破旧钓竿49、好钓竿49、厉害钓竿49、碎岩14；Switch 1/2 使用相同遭遇目录。
- 十分相似的地图不能拼成额外槽位。同组原始地图的物种与等级槽逐项一致；每种方式保留一份完整表：草丛12、冲浪5、破旧钓竿2、好钓竿3、厉害钓竿5、碎岩5。遭遇率沿用原来首条地图记录，不另行平均或推算。
- “变幻洞窟”的多组备选表不再拼为108个槽位，当前目录只使用原始默认超音蝠表。
- 本次不增加受限路线的执行支持，也不修改未知图腾形态等搜索逻辑。目录存在不代表对应自动化路线已经完成实机验收。

## 怎么使用

“野生 / 静态”页的地点栏可直接输入中文或英文关键字。例如输入“不归”或 `lost cave`，再从匹配结果中选择普通房间或有物品房间；也可直接下拉选择。列表按中文名称排序，数字按自然顺序排列，如1号、2号、10号道路。

只输入半截关键字还不算选好地点。此时目标物种列表会清空，旧计划失效；点击生成会提示先从匹配结果选择。不存在的输入不会被加入列表。完整规范中文/英文名称可以直接确认，英文不区分大小写。更换游戏或遇敌方式后，下拉和搜索结果同步更新；仍可用的已选地点保留。

SID 查找页六个“相遇地点”输入也使用同一排序和中英文搜索。只有数量范围内、来源为野生的队伍槽需要有效地点；生成前标明出错槽位并要求重新选择。定点来源和未使用槽不要求野生地点，不会因此阻止采集。

实现见 `assets/game_text.json`、`rng/tenlines_utils.py`、`pyside_app/location_picker.py` 和两页表单接线；测试见 `tests/test_locations.py`、`tests/test_location_picker.py`、`tests/test_pyside_remaining.py`。图形与运行验收以最新 `HANDOFF.md` 记录为准。
