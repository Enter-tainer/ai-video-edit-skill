# 素材库 schema、GPS 轨迹与地名：为什么这么建、口径怎么标、怎么复算

> 适用场景：一次多日外拍（几百条运动相机素材 + 逐日 GPX 轨迹 + 一批带 EXIF GPS 的照片），
> 要在**多个 agent 并行**的情况下把"原始文件 → 技术元数据 → 地理关联 → 内容分析 → 标签 →
> 候选区间 → 成片时间线"串成一条可查询的链，并且事后能对账、能复算。
>
> 本文所有行数/填充率/偏差分布都是**在一个真实库上只读复算出来的**（复算方式见 §9）；
> 凡是没核到的都标了 **未核实**。数值本身是那一次素材的实测值，**可复用的是判据与验证方法**。

**证据强度分级**（冲突时取高者）：

```
A 源码可查        —— 直接读 schema.sql / 工具源码得到的常量与实现
B 库内实测        —— 在库上跑 SQL 数出来的行数、填充率、分布
C 复算实测        —— 用库里的轨迹点/EXIF 重新算出来的数（本文 §5 §6 §7）
D 记录在案        —— 当时的方案/交付文档里的数（可能落后于代码）→ 标"记录值"
E 未核实          —— 只有说法、没有可复算产物
```

---

## 1. 一句话结论

**素材库不是"素材清单"，而是一条链 + 一套口径。** 链决定你能不能查（"有雾的垭口镜头有哪些"），
口径决定你写进花字的数字对不对（"徒步 55.4 还是 132.9 km"）。这两件事**都要在 schema 里落成字段**，
否则它们只存在于某个人（或某个 agent）的上下文里，下一轮就丢了。

最硬的一条教训：**同一个"用 GPX 自己算"的标签下，同一批 8 个拍摄日，
记录值 徒步 64.4 km / 车程 1397 km，而库里现值是 徒步 132.9 km / 车程 1397.0 km**——
车程能对上，徒步差了整整一倍，因为"怎么判定徒步"的规则改过而**没有版本号**（见 §6.6）。
所以：**里程/爬升/海拔一律要写成"数值 + 口径名 + 参数 + 数据源"三件套，跨口径禁止相加。**

---

## 2. 分层：为什么是这些表，而不是一张大表

### 2.1 链的形状

```
源文件          assets                          一文件一行，机器产出，可重建
                ├── audio_stats                音频电平/静音段，机器产出，可重建
轨迹            gpx_tracks / gpx_points        原始点，机器产出，可重建
地理            asset_geo                      每条素材 ← 时间对齐到轨迹点（+ 反查地名）
审片过程        review_frames                  抽出的帧（a/b/c），证明"确实看过"
                sheets / sheet_assets          拼图 + "第几行第几列 ↔ 哪条素材"
判断（人/agent） analyses                       内容分析主表（21 个字段）
                tags / asset_tags              受控词表 + 多对多标签
                segments                       片段内部的候选可用区间
                days                           按天归纳，章节依据
                notes                          人工意见、过程结论、数据坑
成片            edit_plan                      时间线（多版本共存）
                edit_meta                       自由键值袋
视图            v_asset / v_asset_with_tags / v_tagged / v_edit_plan
```

**为什么按这个切**：切表的标准不是"主题相近"，而是**"谁写、多久变一次、丢了能不能重建"**。

| 层 | 谁写 | 可否重建 | 丢了会怎样 |
|---|---|---|---|
| `assets` / `gpx_*` / `audio_stats` | 探针脚本 | **可以**（重跑探针） | 重跑即可 |
| `asset_geo` | 匹配脚本 | 可以（重跑匹配） | 重跑即可 |
| `review_frames` / `sheets` / `sheet_assets` | 抽帧/拼图脚本 | 可以（重跑） | 重跑即可 |
| `analyses` / `tags` / `segments` / `days` / `notes` | **人和 agent 的判断** | **不可重建** | 几十次 AI 审片的结论全没了 |
| `edit_plan` | 分镜脚本 | 可重建但代价高（是决策产物） | 时间线没了 |

**这条分层的唯一目的**：让"可重建的"随便重跑，"不可重建的"有一道墙保护。

### 2.2 为什么 `analyses` 必须和 `assets` 分开

**为什么**：`assets` 是探针的产物（ffprobe 跑一遍就有），`analyses` 是**付费且不可重来**的判断。
两者生命周期完全不同；合在一张表里，任何一次重新扫盘都会碰到"要不要覆盖人工字段"的问题。

**怎么验证**：`SELECT COUNT(*) FROM assets a LEFT JOIN analyses an ON an.asset_id=a.id WHERE an.asset_id IS NULL`
——覆盖率为 0 说明审片跑满了；**更重要的是反过来验证"重新扫盘不会删掉 analyses"**，见 §4.1（这是个真坑）。

**关键列**（`analyses`，实测 21 个字段全部 151/151 填满，除 `best_in/best_out` 133/151）：

| 列 | 作用 | 为什么要有 |
|---|---|---|
| `scene` / `subject` / `action` | 场景/主体/动作 | 检索的最小三元组 |
| `shot_size` / `camera_move` | 景别/运镜 | 拼接节奏靠它（静 vs 动、远 vs 近） |
| `time_of_day` / `weather` / `light` | 时间/天气/光位 | 决定能不能和相邻镜头接得上 |
| `quality` / `issues` / `usable` | 质量/问题/可用 | 初筛：**AI 只判得出"技术缺陷"，判不出"这一眼好不好看"** |
| `keep_score` (0–5) | 剪辑价值 | 排序用；写入时 clamp 到 0–5 |
| `role` | opening/establishing/body/detail/transition/ending/broll | **结构化角色**，让"开场只要 establishing"变成一条 SQL |
| `summary` | 一句话描述 | 人和 agent 之间唯一的低成本接口 |
| `best_in` / `best_out` | 建议采用区间（秒） | 把"这段不错"变成可渲染的入出点 |
| `analyzed_by` / `analyzed_at` | 谁、什么时候 | **并行写入的审计字段**：实测 151 行来自 **10 个写入者**（1 个主会话 + 9 个 agent） |
| `frames_seen` / `confidence` | 看过几帧 / 置信度 | 防"没看帧就编"（见下） |

**为什么 `role` 是枚举而不是自由文本**：实测分布 `body 38 / establishing 34 / transition 32 /
broll 28 / detail 14 / ending 4 / opening 1`——只有枚举才能这样数，也才能发现
**"opening 只有 1 条"这种结构性缺口**（开场只能靠快切拼，因为真正适合开场的长镜只有一条）。

**为什么 `frames_seen` 这种字段值钱**：它把"我看过画面"和"我从文件名猜的"分开。
只有看过帧才说得出的细节（画面里有一只手、仪表台入镜、地平线倾斜）才能进 `issues`。

### 2.3 为什么标签要 `tags` + `asset_tags` 两张表

**为什么**：一条素材天然有多个标签，标签又天然被多条素材共享 → 多对多。
更重要的是**受控词表**：标签自由生长会得到"雾/有雾/大雾/晨雾"四个同义词，检索就废了。

**关键列**：`tags(name UNIQUE, kind)`、`asset_tags(asset_id, tag_id, confidence, source)`，
主键 `(asset_id, tag_id)` 保证幂等。

**为什么 `kind` 是必需的**：实测 58 个标签分成 6 类
`scene 14 / subject 14 / quality 9 / mood 8 / motion 7 / role 6`。
有了 `kind`，"按语义找镜头"才能拆成可执行的条件
（`kind='scene' AND name LIKE '%雾%'`）；实测**没有任何 `kind='place'` 的标签**——
因为地点走的是 `asset_geo.place` 这条地理链路，**同一件事不要有两条真相路径**。

**怎么验证**：`SELECT COUNT(DISTINCT asset_id) FROM asset_tags` 应等于素材总数（实测 151/151，
共 679 条关联，平均 4.5 个标签/条）；`SELECT COUNT(*) FROM asset_tags at LEFT JOIN tags t ... WHERE t.id IS NULL`
应为 0（外键保证）。

### 2.4 为什么审片过程要入库（`review_frames` / `sheets` / `sheet_assets`）

**为什么**：并行审片时，"agent 看到的第 3 张拼图的第 7 格"必须能唯一还原成"哪条素材的第几秒"。
如果这个映射只存在于 prompt 里，事后**无法复核结论是怎么得出的**，也无法重跑。

**关键列**：`review_frames(asset_id, pos, t_sec, path)`，`UNIQUE(asset_id,pos)`；
`sheets(day, seq, path, cols, rows, n_assets, status, assignee)`，`UNIQUE(day,seq)`；
`sheet_assets(sheet_id, asset_id, row, col)`，主键 `(sheet_id, asset_id)`。

**怎么验证**：`review_frames` 实测 453 = 151×3（`pos` 恰好 a/b/c 各 151），
说明**"每条素材抽 3 帧"这条纪律被执行了**；`sheet_assets` 实测 151 行、
**没有任何素材被列两次**（`GROUP BY asset_id HAVING COUNT(*)>1` = 0），
说明每格归属唯一。任何一条不成立就说明拼图/映射脚本漏了或重了。

**诚实清单**：`sheets.status` 22/22 有值但**全是 `'pending'`**，`assignee` 0/22——
这两列的"派工"用途实际上没走库（派工是带外的）。**列留着，但别信它。**
`days.weather`、`days.highlights`、`edit_meta`（整表 0 行）、
`audio_stats.noise_floor_db`/`note`、`tags.kind='place'` 同理：**声明了但这次没用上**。

### 2.5 为什么时间线要 `variant` 分区

**为什么**：同一批素材会并行存在多个版本的时间线（长版/短版/试片版）。
如果只有一个 `position` 序列，写完一个版本就把另一个覆盖了。

**做法**：`edit_plan(id, position, asset_id, t_in, t_out, section, purpose, transition, note, created_at, variant)`
——`variant` 是**后加的列**（`ALTER TABLE ... ADD COLUMN variant TEXT DEFAULT 'v1_5min'`，见 §3），
`position` 在**每个 variant 内部从 1 开始**。

**怎么验证**：实测 247 行分 5 个 variant（35 / 100 / 56 / 31 / 25），
每个 variant 的 `MIN(position)=1` 且 `COUNT(*)=COUNT(DISTINCT position)`。
**任何读 `edit_plan` 的查询都必须带 `WHERE variant=?`**，否则会把 5 个版本混成一条时间线——
这是这个 schema 里最容易犯的错。写入方每次先 `DELETE FROM edit_plan WHERE variant=?` 再插，
所以**没有"半个版本"的状态**（重跑幂等）。

**另外**：247 行里 **27 行 `asset_id IS NULL`**——时间线上的标题卡/黑场/纯文字卡不对应任何素材。
**建模时就要允许这种行**，否则会被迫为"卡片"造假的素材行。

### 2.6 为什么人工意见单独一张 `notes`

**关键列**：`notes(scope, ref, body, author, created_at)`，
`scope ∈ day | asset | sheet | global | question`，`ref` 是**文本**引用而不是外键。

**为什么 `ref` 故意不做外键**：实测 24 条里 `sheet 22 / asset 1 / global 1`。
人工意见的价值恰在于**它可以在实体被重建/删除之后依然活着**（见 §4.1 的级联坑）：
"这条素材的相机时钟是 UTC"这种结论，比它指向的那一行技术元数据更耐久。

**怎么验证**：`SELECT scope, COUNT(*) FROM notes GROUP BY scope`——
如果 `sheet` 条数 ≠ 拼图张数，说明有拼图的审片结论没落库，只活在某个 agent 的对话里。

### 2.7 视图：把三张表拼成"一次查询"

`v_asset` = `assets` + `asset_geo` + `analyses`（都是 `LEFT JOIN`，所以未分析的素材也在），
`v_asset_with_tags` 再挂上 `GROUP_CONCAT` 的标签串，`v_tagged` 是"素材×标签"的长表，
`v_edit_plan` 把时间线挂上素材号和时长。**只读查询一律走视图**，字段名背一次就够。

**注意（源码可判定，未实测）**：`v_asset` 的 `SELECT` 里引用了 `g.cum_dist_km / g.cum_ascent_m / g.move_mode`，
而 `CREATE TABLE asset_geo` 里**没有这三列**（它们是后来 `ALTER TABLE` 加的，见 §3）。
所以**"先跑 schema 迁移、再跑指标脚本"这个顺序是硬依赖**：
在一个没跑过指标脚本的库上执行建视图脚本会直接报 `no such column`。
**修法**：把这三列写进 `CREATE TABLE`（新库）或让视图与迁移在同一个脚本里跑。

---

## 3. 哪些是后来加的（迁移轨迹）

**实测**（`sqlite_master` 里的 DDL 文本会保留 `ALTER TABLE` 追加的尾巴，这是最可靠的考古手段）：

| 对象 | 来源 | 证据 |
|---|---|---|
| 15 张表 + 4 个视图 | `tools/schema.sql`（幂等的 `CREATE ... IF NOT EXISTS` + `DROP VIEW`/`CREATE VIEW`） | schema.sql 全文 |
| `audio_stats` 表 | **运行时由音频脚本建**（`CREATE TABLE IF NOT EXISTS audio_stats (...)`） | 脚本 DDL |
| `day_metrics` 表 | **运行时由指标脚本建** | 脚本 DDL |
| `asset_geo` + `cum_dist_km REAL, cum_ascent_m REAL, move_mode TEXT` | `ALTER TABLE asset_geo ADD COLUMN`（带 `PRAGMA table_info` 检查，幂等） | DDL 里列在三列被单行追加在 `)` 前 |
| `edit_plan` + `variant TEXT DEFAULT 'v1_5min'` | `ALTER TABLE edit_plan ADD COLUMN variant ...` | 同上 |

**为什么这件事必须写进文档**：`schema.sql` 是"声明式真相"，但**库里的真相是 schema.sql + 4 处运行时迁移**。
只读 `schema.sql` 会以为 `asset_geo` 没有里程列，只读库会以为这些都是建库时就有的。
**新建库时把这 4 处迁移合进 `schema.sql`，就少一个"新环境跑不起来"的失败模式。**

**怎么验证**：`SELECT sql FROM sqlite_master WHERE name IN ('asset_geo','edit_plan')`，
看追加列的写法（追加列会挤在同一行末尾，与手写的对齐格式不同）。

---

## 4. 唯一写入口与并发

### 4.1 规则

**规则**：**agent 一律不直接连库写**，只通过一个写库助手（本项目是 `tools/dbwrite.py`），
它做四件事：

1. **字段白名单**：不在 `ANALYSIS_FIELDS` 里的键直接报错退出（防 schema 漂移）。
2. **枚举校验**：`quality ∈ {excellent,good,fair,poor}`、`role ∈ {opening,...,broll}`，非法值报错。
3. **数值 clamp / 类型归**：`keep_score` clamp 到 0–5，`usable` 归成 0/1。
4. **幂等 upsert**：`analyses` / `days` 用 `INSERT ... ON CONFLICT(...) DO UPDATE`；
   标签先 `INSERT OR IGNORE` 进词表再取 id，再 upsert 关联表。

**连接层**：`PRAGMA foreign_keys=ON`、`PRAGMA busy_timeout=60000`、
`journal_mode=WAL`（建库时设置、随文件持久化，实测库报 `wal`）——
WAL 让"多个 agent 并发写 + 一个只读查询"不互相阻塞；
`busy_timeout` 让并发写排队而不是立刻抛 `database is locked`。

**怎么验证**：
- `PRAGMA journal_mode` 返回 `wal`；
- 故意塞一个非法字段/非法枚举，抓 `SystemExit`（这是个**测试用例**，不是文档承诺）；
- `SELECT analyzed_by, COUNT(*) FROM analyses GROUP BY analyzed_by` 应给出多个写入者
  （实测 10 个，合计 151 行 = 100% 覆盖）——**这是"并行写库真的成功了"的唯一直接证据**。

**边界（诚实）**："唯一写入口"约束的是**跨 agent 的判断类写操作**。
流水线脚本（指标、地理编码、分镜生成）各自写自己那几张表（`asset_geo`/`day_metrics`/`days`/`edit_plan`），
并没有走这个助手。所以更准确的说法是：**一表一个所有者**，不是"全库一个写入口"。

### 4.2 一个实测过的坑：父表用 `INSERT OR REPLACE` 会换 id 并级联删子表

**事实**：素材入库用的是
`INSERT OR REPLACE INTO assets (asset_no, kind, filename, ...)`（**不指定 `id`**），
而 `asset_no` 是 `UNIQUE`。在 `foreign_keys=ON` 下，我在**库的临时副本**上复现了两种结果：

| 情形 | 结果（临时副本实测） |
|---|---|
| 库里已有 `edit_plan` 行 | 直接 `IntegrityError: FOREIGN KEY constraint failed`（`edit_plan.asset_id` 没有 `ON DELETE` 子句 → 默认 `NO ACTION`），**回滚，什么也没坏** |
| 清空 `edit_plan` 后再 REPLACE | **换 id（1 → 152）**，并且因为 `ON DELETE CASCADE`：`analyses 151→150`、`asset_geo 151→150`、`asset_tags 679→675`、`review_frames 453→450`、`segments 103→102`——**这条素材的全部判断类数据被静默删掉**；`notes` 不受影响（`ref` 不是外键，实测 24 条全在） |
| 改用 `INSERT ... ON CONFLICT(asset_no) DO UPDATE` | **id 不变**，`assets/analyses/asset_geo` 全为 151、`edit_plan` 247 行全在 |

**为什么**：`REPLACE` 的语义是"先 `DELETE` 冲突行再 `INSERT`"，删父行会触发级联；
而 `assets.id` 是代理键，重插会拿到新值，所有 `asset_id` 外键随之失配。

**规则**：**父表（被 `ON DELETE CASCADE` 指向的表）永远不要用 `INSERT OR REPLACE` 重扫**，
用自然键上的 upsert（`ON CONFLICT(asset_no) DO UPDATE`）；或者把 `asset_no` 直接做主键。

**怎么验证**：把库**复制到临时目录**，对一条素材重放入库语句，然后数
`assets/analyses/asset_geo/asset_tags/review_frames/segments` 六张表的行数
以及那条素材的 `id` 有没有变。**永远不要在真库上做这个实验。**

---

## 5. GPS 轨迹：入库 → 对齐 → 校验

### 5.1 入库：原始点单独一张表

`gpx_tracks(name UNIQUE, path, t_start_utc, t_end_utc, n_points, lat/lon/ele 的 min/max)` +
`gpx_points(track_id, t_utc, t_epoch, lat, lon, ele)`，索引 `(track_id, t_epoch)`。

**为什么 `t_epoch`（整数秒）和 `t_utc`（ISO 文本）都存**：文本给人看/对账，
整数用于 `searchsorted` 二分与算术（时间对齐和滑窗全靠它）。

**为什么先按时间排序再插**：实测 11 段轨迹共 **297,761 个点**，且
`SUM(gpx_tracks.n_points)` 与 `COUNT(gpx_points)` **完全相等**——这是一个便宜的入库自检。
**ele 没有一个是 NULL**（实测 0 行缺失）。

**关键陷阱：轨迹天数 ⊃ 拍摄天数。** 实测 `gpx_tracks`/`day_metrics` **11 天**，
而 `days`/`assets` 只有 **8 天**——有 3 天是纯转场/集合日，只有轨迹没有素材。
**规则**：`days` 与 `day_metrics` 的覆盖范围**不保证相同**，
任何跨表统计都要显式确认"你要的是拍摄日还是行驶日"，否则分母就错了。

### 5.2 对齐：用拍摄时刻去轨迹里反查最近点

`asset_geo` 每行：`track_id, t_epoch, lat, lon, ele, dt_sec, match_quality, place, area`。

**规则**：只用**时间**做匹配（素材的 UTC 拍摄时刻 ↔ 轨迹点 epoch，二分找前后各一个取更近的），
并用 **`dt_sec ≤ 300s`** 设上限；分段函数
`exact ≤10s / near ≤60s / far ≤300s / none`。

**为什么用时间而不是几何**：这是唯一能自动跑的匹配方式（素材本身没有坐标）；
`dt_sec` 就是它的**不确定度**，必须落库。

**实测分布**：`exact 148 / near 1 / far 1 / none 1`；
`dt_sec` 平均 6.1s、中位 0.0s、**最大 718s**。
718s 那一条解释了为什么 `match_quality` 必须是一等公民：**最后一天那段轨迹有 ~12 分钟的空洞**，
于是那天的 3 条素材里 1 条判 `none`（偏差 718s）、1 条判 `far`（184s）。

**规则（很硬）**：**`match_quality` 为 `far` / `none` 的行，坐标不可用于花字/地名**，
只能当作"当天大概在哪"。查询时必须显式写
`WHERE match_quality IN ('exact','near')`，**不要静默地把它们当有效坐标**。

**怎么验证**：
```
SELECT match_quality, COUNT(*) FROM asset_geo GROUP BY match_quality;
SELECT a.asset_no, a.day, g.match_quality, g.dt_sec FROM asset_geo g JOIN assets a ON a.id=g.asset_id
 WHERE g.match_quality IN ('far','none') OR g.dt_sec > 60 ORDER BY g.dt_sec DESC;
```
第二句是**必查清单**——它只有 2 行，但它决定了"哪几条素材不能往上写字"。

### 5.3 位置校验：拿第二条独立证据去打坐标

**规则**：照片有自带 EXIF GPS，轨迹有独立记录的两个点源。
把照片的 `DateTimeOriginal` 对齐到**当天**轨迹的最近点，
算两者水平距离 `d`，得到一个**偏差分布**。

**为什么**：`d` 很小只能说明"照片坐标与轨迹自洽"，
**`d` 很大才是真信息**——它说明两份记录里至少有一份错（或照片被后期改动/时区错）。

**实测（本文独立复算，34 张照片）**：

| 指标 | 实测 |
|---|---|
| 匹配成功 | 34/34（无一张落在轨迹时间范围外） |
| 最大偏差 | **11.75 m** |
| 平均偏差 | **1.45 m** |
| ≤10 m | **32/34** |
| ≤15 m / ≤50 m / ≤100 m | 34/34 / 34/34 / 34/34 |

逐日最大偏差：`0.00 / 1.47 / 5.06 / 1.48 / 0.76 / 10.32 / 11.75 / 8.57` m。

> **对记录值的一处修正（D → C）**：当时的文档写的是"34 张全部落在 **0.00–0.01 km** 内"。
> 独立复算的结果是**全部 ≤ 12 m、32/34 ≤ 10 m**。四舍五入到 0.01 km 才成立，
> **请用"≤12 m（32/34 ≤10 m）"这个写法**——它自带不确定度，而且可复算。

**怎么验证（可照抄）**：读照片 EXIF GPS + 拍摄时间 → 按日期取当天轨迹点数组 →
`searchsorted`/线性找最近时刻点 → haversine。
**注意**：EXIF 时间是**本地时间（无时区）**，轨迹/素材是 **UTC**，
必须显式补上时区偏移再比——本项目混过这个坑（同一件事里出现过
"把 `shot_at_local` 当成 UTC 对齐"的错误，见 §9 未核实清单第 3 条）。

### 5.4 位置校验真正的价值：它能证伪的往往是**标签**，不是坐标

**实测案例（通用化描述）**：34 张里只有 1 张的坐标与它当时的**字幕**对不上——
那张照片的 `d = 1.47 m`（坐标完全自洽），但它拍在**距字幕所写的那处湖泊还有约 11 km**的路上：
同一时刻的轨迹点就在现场（`dt = 0.6 min`），而当天"湖边素材"的第一条是 **1 小时后**才开机的。

**结论/规则**：
1. **"坐标与轨迹一致" ≠ "标本上的地点名是对的"。** 校验要拿坐标去对**它被标成什么**，
   而不是只对坐标本身。
2. **修正动作是把地点标签挪到真正在场的镜头**（把"某湖｜徒步 X km"挪到当天第一条
   轨迹确实在湖边的镜头），而不是删照片。
3. 顺带发现：那处湖泊当天拍的 5 张**全是长焦小动物特写，没有一张湖的风景**——
   **"某处有照片"不等于"某处有该处的风景照"**，选章节封面时要用 `place` 聚合出来看，
   不要凭"我们那天去过"的假设。

**怎么验证**：对每条"带地点名的字幕/花字"，取它挂的素材的 `asset_geo.place` 与该素材
`shot_at_*`，和文案里的地名/里程逐条比；不一致就查那一分钟的轨迹点。

### 5.5 逆地理编码出地名（供字幕用）

**规则**（`tools/geocode.py`）：**先按拍摄点聚类（阈值 3 km，沿时间顺序做单链聚类），
每个簇只请求一次逆地理编码，结果写入整簇 + 一个本地 JSON 缓存**；地名标签按优先级拼
`名称 · tourism/attraction → hamlet/village → town/city_district → city/county → state_district`，
取前 2 段；`area` 单独取 `county/city/state_district/state`。

**为什么聚类**：几十个点要是逐点请求，既慢又违反公共服务的限流礼貌；
聚类把请求数压到"每簇一次"，再叠加**磁盘缓存（键 = 四舍五入到 0.0001° 的坐标）**。
`--force` 才重算，默认"当天素材已全部有地名就跳过"——**幂等**。

**为什么标签要拼而不是直接用 `display_name`**：`display_name` 太长且层级顺序不适合做字幕；
按上面的优先级最多取两段，得到"某地 · 某景区"这种可直接上屏的短名。

**怎么验证**：
```
SELECT COUNT(*), COUNT(place), COUNT(area) FROM asset_geo;   -- 实测 151/151/151
SELECT day, COUNT(*) FROM asset_geo g JOIN assets a ON a.id=g.asset_id
 WHERE place IS NULL GROUP BY day;                            -- 实测空
```
**地名口径的先后**：外部权威记录 > 逆地理编码 > 早期文档。
实测中**早期文档的个别地名在后期被权威记录纠正过**（把"路过某镇"写成了"进了某景区"之类），
所以 `calibrate_route.py` 的存在意义就是**用外部口径覆盖自动结果并留下一条 `notes` 说明**。
**规则：地名一旦被外部口径覆盖，就把覆盖动作写成一条 `notes`（scope=global），别只改字段。**

---

## 6. 里程 / 爬升：口径问题（本文最贵的一节）

### 6.1 算法做了什么（`tools/metrics.py`）

1. 海拔毛刺：偏离**中位数 900 m** 以上的点，拉回中位数；
2. 相邻点 haversine 距离 → 瞬时速度 **> 200 km/h** 记为 GPS 跳点，距离计 0；
3. 累计里程/爬升；**30 s 滑动窗口速度**；
4. **`速度 ≤ 4.0 m/s (14.4 km/h)` 判为徒步**，其余判为车行；
5. 把"**只累计徒步段**"的 `cum_dist_km` / `cum_ascent_m` 与 `move_mode` 写回每条素材；
6. 每天一行写进 `day_metrics`（`track_km / walk_km / drive_km / ascent_m / walk_ascent_m / max_speed_kmh / ...`）。

### 6.2 一个静默的语义坑：`asset_geo.cum_dist_km` 是**徒步累计**，不是总里程

**事实**（源码 + 库内实测）：`cum_dist_km` / `cum_ascent_m` 写的是 `cum_walk_d` / `cum_walk_up`
——**只加徒步段**。但列名里没有 "walk"，而且 `v_asset` 把它当通用字段暴露出去。
实测佐证：23 条 `move_mode='drive'` 的素材，其 `cum_dist_km` 落在 **0.19–10.58 km**、
`cum_ascent_m` 落在 **3–223 m**（都是"当天徒步累计"的量级），
而当天 `track_km` 是 200 km 量级。**所以不是"当天开了多远"。**
另一个佐证：逐日 `MAX(cum_dist_km)` 全部 **小于** 当天 `day_metrics.walk_km`
（如 15.78 < 24.08），说明它确实被限制在徒步累计内。

**规则**：
- 要么把列名改成 `cum_walk_dist_km`，要么在视图里把语义写进列名；
- **写花字时先看 `move_mode`**：`drive` 的镜头不要用它当"今天走了多远"；
- 混用会得到"在车上说今天走了 5 km"这种错误。

**怎么验证**：
```
SELECT g.move_mode, COUNT(*), ROUND(MIN(g.cum_dist_km),2), ROUND(MAX(g.cum_dist_km),2)
  FROM asset_geo g GROUP BY g.move_mode;
SELECT COUNT(*) FROM asset_geo g JOIN assets a ON a.id=g.asset_id JOIN day_metrics m ON m.day=a.day
 WHERE g.cum_dist_km > m.walk_km + 0.01;   -- 实测 0，说明它确实被 clamp 在当天徒步里程内
```

### 6.3 口径敏感度：同一批轨迹，能算出的数差一个量级

**本文复算**（同样 8 个拍摄日、同一批轨迹点，只换算法参数）：

| 口径 | 8 天合计 |
|---|---|
| 距离：逐点求和，不做跳点过滤 | **1565.0 km** |
| 距离：丢弃 >200 km/h 跳点 | **1529.9 km**（−2.2%） |
| 徒步里程：徒步判定阈值 **4.0 m/s** | **132.9 km** |
| 徒步里程：阈值 **3.0 m/s** | **110.1 km** |
| 徒步里程：阈值 **2.0 m/s** | **97.0 km**（比 4.0 低 **27%**） |
| 爬升：逐点正差值直接累加（≈ 库内实现，差 0.4%，见 §6.4 注） | **39,389 m** |
| 爬升：中位 5 + 均值 5 平滑后累加 | **36,029 m** |
| 爬升：平滑 5 + 每步 **≥3 m** 才计 | **5,549 m** |
| 爬升：平滑 11 + 每步 **≥5 m** 才计 | **5,088 m**（比裸累加低 **87%**） |

**结论**：
1. **距离口径比较稳**（跳点过滤只影响 2%），**徒步里程与爬升极度不稳**——
   徒步里程换个阈值差 27%，爬升换个平滑/阈值差 **87%**。
2. 裸累加爬升就是**在累加噪声**：8 天 39 km 爬升 ≈ 每天 4.9 km，
   而权威口径里单日徒步爬升是**几百米**量级（实测 500–866 m/天），**差 5–8 倍**。
   **爬升必须"先平滑 + 再设最小步长阈值"，并且阈值要写进文档。**
3. **所以"车行 1664 vs 1260 km""徒步 55.4 vs ... km"这类争议，多半不是谁算错了，
   而是**没写清口径**——要么是算法参数不同，要么是**覆盖范围不同**（12 天 vs 8 天）。**

### 6.4 记录值 vs 库内值：一次真实的"口径漂移"

| 口径 | 徒步（8 个拍摄日） | 车行（8 个拍摄日） | 爬升 |
|---|---|---|---|
| **记录在案（D，当时文档）** | **64.4 km** | **1397 km** | **4984 m** |
| **库内现值（B，本文实测）** | **132.9 km**（`SUM(walk_km)`） | **1397.01 km**（`SUM(drive_km)`） | 39,228 m（`SUM(ascent_m)`，先做 900 m 中位去毛刺再裸累加） |
| **本文复算（C，§6.3 平滑+阈值口径）** | 97.0–132.9 km（随阈值） | 1529.9 km（track） | 5,088 m（平滑 11 + ≥5 m） |

> 两个"裸累加"爬升的差：**39,389 m**（§6.3，直接对原始 `ele` 求正差值）
> vs **39,228 m**（库内，源码先做 900 m 中位去毛刺再累加）——**相差 0.4%**，
> 说明"去毛刺"这一项在这种量级下几乎不起作用，真正决定数量级的是**平滑 + 最小步长阈值**。

**读法**：
- **车行能对上**（1397 vs 1397.01，说明这套"总里程 − 徒步里程"的减法口径没变）；
- **徒步差一倍**（64.4 vs 132.9）——同一个"GPX 自算"标签下，**判定规则被改过而没留版本号**；
- 记录值 4984 m 与本手册复算的"平滑 + 阈值"口径 5088 m 才是同一量级，
  **跟库内裸累加的 39,228 m 差近 8 倍**（记录值究竟用了哪套平滑参数：**未核实**）。

**规则（直接可执行的）**：
1. `day_metrics` 的每一列都要配一个**口径名**（存在哪套参数、谁跑的、什么时候跑的）。
   最低成本做法：在同一个库里写一张 `metric_versions(metric, source, algo, params, computed_at)`，
   或者至少把口径写进 `notes(scope='global')`。
2. **任何时候引用里程/爬升，必须写出"数据源 + 算法 + 参数"**，
   例如"GPX 自算，30 s 滑窗，徒步阈值 4.0 m/s"或"外部权威记录"。
3. **跨口径的数不可相加、不可比较、不可混写在同一屏字幕里。**
   本项目最终的成片字幕**统一改用外部权威口径**（见 §6.5），
   把 GPX 自算的数留在库里当参考——**这是对的做法**。

### 6.5 外部权威口径 vs 自算口径：一个具体的 10%+

**记录在案的外部权威口径**（来自一次路线校准，`tools/calibrate_route.py` 的说明文字）：

| 量 | 权威口径 | 自算口径 | 差异 |
|---|---|---|---|
| 徒步（**整段行程 12 天**） | **55.4 km**（补上一段未计的 2.9 km 则为 59.7） | 记录值 64.4 / 库内 132.9（均为 8 天） | 口径不同，**不可直接比** |
| 车行（整段行程 12 天） | **1664.0 km** + **摩托 10.8 km** | — | 摩托**单列**，不并入车行 |
| 车行（本片覆盖的 **8 天**） | **1260.3 km** | 库内 `SUM(drive_km)` = **1397.0 km** | **+10.9%**（GPX 漂移虚高） |

**规则**：
1. **先固定"天数范围"再比数**：12 天口径和 8 天口径的车行里程差 400 km，
   两者的数放在一句话里就是错的（本项目文档明确写了"两个口径不可相加"）。
2. **摩托必须单独一类**，不能并进"车行"，更不能并进"徒步"（见 §6.6）。
3. 自算里程比权威口径**系统性偏高约 10%**，原因是停车漂移与低速段被计入——
   **自算口径适合做"相对比较"（哪天多、哪天少），不适合直接上屏。**

### 6.6 摩托/车行不能被算成徒步（这一条的代价最大）

**实测（一个"汽车 + 摩托 + 徒步"混合日）**：

| 口径 | 该日徒步 | 该日车行 | 该日总里程 |
|---|---|---|---|
| 外部权威（人工分段） | **10.1 km** | 汽车 9.5 + 68 = **77.5**，摩托 4.9 + 5.9 = **10.8** | ≈ **98.4 km** |
| 库内（纯速度阈值，4.0 m/s） | **17.4 km** | **83.9 km** | 101.3 km |

**读法**：库内徒步 17.4 km 比真实徒步 10.1 km 多了 **7.3 km**，
而那天摩托总共才 10.8 km —— **约 2/3 的摩托里程被速度阈值判成了徒步**。
（同一天 36 条素材在库里 `move_mode` **全部**是 `walk`。）

**为什么会错**：上坡烂路上的摩托速度会掉到步行区间；
而"停车漂移"也会被算成慢速移动。**单一速度阈值无法区分"人在走"和"车在慢行"。**

**规则**：
1. **"徒步里程"必须来自分段证据**（人工/权威记录给出的分段点，或"停车点 + 轨迹形状"的联合判断），
   速度阈值只能做**初筛**。
2. 那天还有一段**已取消的路线**——权威口径明确 "那段我们没走"。
   **取消的路段绝不能被算进任何里程**，否则数字直接虚高。
3. **上屏的徒步数字用权威口径**；库内自算值只做内部参考，并**标注"含摩托/漂移"**。
4. 画面里出现"车 X km + 摩托 Y km + 徒步 Z km"时，**三段必须来自同一份权威分段**。

**怎么验证**：挑一个已知是"复合交通"的日子，把库内 `walk_km` 与权威徒步量相减；
差额若与该日摩托量同量级，就说明阈值把摩托吃进徒步了。

### 6.7 海拔读数也要标口径（设备 vs 权威）

**记录在案**：同一个垭口，**设备读数比权威记录高约 35 m**（4606 m vs 4571 m）；
而"全程最高点在哪个拍摄日"这种结论**曾被早期文档写错**（写成了另一个日子），
后来按库里的 `ele` 排序复算才纠正。

**规则**：
1. 每一个海拔数字都要带**来源**（设备气压高度 / 权威记录 / DEM），
   **不同来源不可混用**（差值可达几十米，足以改变"这是不是 4600+ 的垭口"这类文案）。
2. **"最高点/最陡点/最远点"必须用 SQL 从库里的 `ele`/`day_metrics` 复算**，
   不要凭行程印象写。
3. 排序/取极值时提醒：`day_metrics.ele_max` 来自**当天素材所在位置**的采样，
   而 `gpx_tracks.ele_max` 来自**整段轨迹**——后者才代表"那天到过的最高海拔"。

---

## 7. 验收与对账

### 7.1 与文件系统对账（必须做，且便宜）

**规则**：库里的"条数 / 总时长 / 总大小"要和**源目录**逐项对上；
差一条就说明筛选正则或探针漏了。

**实测（本文复算）**：

| 项 | 库内 | 文件系统（源目录按同一正则筛） | 一致 |
|---|---|---|---|
| 条数 | 151（全是视频） | 151（全是 `.MP4`） | ✅ |
| 总大小 | 55.11 GiB（59,171,455,858 B） | 55.11 GB | ✅ |
| 总时长 | 71.58 min（4295.06 s） | （由探针得出） | — |
| 逐日条数 | 35/36/16/8/7/10/36/3 | — | 合计 151 ✅ |

**为什么"逐日"也要数**：总数对得上但某天少一条，往往正是**筛选正则漏了一天的命名**。
实测逐日体积 `7.05/9.09/4.89/2.16/1.96/3.38/25.78/0.79 GiB`——
**最后一天只有 3 条 0.79 GiB**，这种"断崖"要在对账时就看见（它是行程尾段）。

**怎么验证**：`COUNT(*)` / `SUM(duration_s)` / `SUM(size_bytes)` 三句 SQL，
对着文件系统的计数与 `Sum(Length)`；**两个数写进交付说明**，别只说"对上了"。

### 7.2 内部一致性（一趟 SQL 全查完）

```
-- 子表覆盖率：都该等于素材总数
SELECT (SELECT COUNT(*) FROM assets) assets, (SELECT COUNT(*) FROM analyses) analyses,
       (SELECT COUNT(*) FROM asset_geo) asset_geo, (SELECT COUNT(*) FROM audio_stats) audio;
-- 实测 151 / 151 / 151 / 151

-- 审片帧数 = 素材数 × 每条的抽帧数
SELECT COUNT(*) FROM review_frames;                       -- 实测 453 = 151×3

-- 每条素材在拼图里恰好出现一次
SELECT COUNT(*) FROM (SELECT asset_id FROM sheet_assets GROUP BY asset_id HAVING COUNT(*)>1);  -- 0

-- 轨迹点：汇总字段 vs 明细行数（两者应相等）
SELECT (SELECT SUM(n_points) FROM gpx_tracks) AS sum_n_points,
       (SELECT COUNT(*) FROM gpx_points)      AS detail_rows;   -- 实测 297761 = 297761

-- 每天一条且 position 连续
SELECT variant, COUNT(*), COUNT(DISTINCT position) FROM edit_plan GROUP BY variant;
-- 35/35, 100/100, 56/56, 31/31, 25/25

-- 没人分析的素材
SELECT COUNT(*) FROM assets a LEFT JOIN analyses an ON an.asset_id=a.id WHERE an.asset_id IS NULL;  -- 0
```

### 7.3 位置校验对账（§5.3）

**规则**：`≤10 m` 与 `≤100 m` 两档都报；**最大偏差**必须报（它决定了能不能拿坐标写花字）。
实测 `max 11.75 m / mean 1.45 m / ≤10 m 32/34 / ≤100 m 34/34`。
**如果最大偏差是几百米，那批坐标就只配做"当天在哪"，不配进位到小数点后 5 位。**

### 7.4 对账之后要留什么

一份"验收小抄"：条数/时长/体积、每张子表的覆盖率、每个 variant 的镜头数、
照片偏差分布、以及**每一个上屏数字的口径名**。
**没有口径名的大数字，下一轮一定会被人（或另一个 agent）重新算成另一个值。**

---

## 8. Embedding：本次**未采用**（如实记录）

### 8.1 事实（可查证）

- **工具源码里搜不到 embedding 相关实现**：在 `tools/*.py` 全量搜索 `embed`，**0 命中**。
- **库里没有任何 embedding 列/表**：遍历 `sqlite_master` 的全部表与视图的列名，
  搜 `emb / vec / clip / faiss / semantic`，**0 命中**；全库 DDL 文本搜 `embed`，**0 命中**。
- 检索与去重实际靠的是：**结构化字段**（`scene/subject/weather/light/camera_move/role`）+
  **受控标签**（`tags`/`asset_tags`，实测 679 条关联、58 个标签）+ **抽帧目视**。

**结论：本次项目中 embedding 既没有被实现，也没有被评估，更没有实测效果。
下面 8.2 是"值得考虑的场景"（设计推测），不是本项目的结果。**

### 8.2 哪些环节**可能**值得考虑（全部 **未核实 / 未实测**）

| 场景 | 现在怎么做的 | embedding 若上的话，可能补什么 | 状态 |
|---|---|---|---|
| 素材检索 | 结构化字段 + 标签 + 关键词 SQL | 按自然语言找镜头（"有雾的垭口""逆光的长草坡"） | **未核实** |
| 相似镜头去重 | 同一天同一段路靠人眼在拼图上比 | 把"几乎一样的镜头"自动聚成一簇，只留最好的一条 | **未核实** |
| 章节封面/代表帧挑选 | 按 `keep_score` + 标签 | 让"代表帧"覆盖更多语义簇，减少同质重复 | **未核实** |
| 字幕/花字措辞与画面对齐 | 手写 | 检查文案语义与画面语义是否离谱 | **未核实** |

**已知的替代性证据**：本项目里"同质化重复镜头"是靠**人工在看拼图时发现的**
（同一天同一段路常常十几条几乎一样），并用"只留最好的一条"处理。
embedding **是否能做得更好，本次没有验证**。

### 8.3 若要上，至少要能回答（**未核实**）

1. **用什么模型、跑在哪**（本地显存/CPU 是否放得下；这批素材是 4K60、量大）。
2. **抽帧粒度**：按条抽（用现成的 `review_frames` 的 a/b/c 三帧）还是按秒抽样；
   抽样越密成本越高。
3. **向量存哪**：SQLite 不是向量库，需要额外的向量索引或扩展；**与现有"单文件库、可拷贝、可 SQL 查"的形态冲突**。
4. **验收怎么定**：必须有**对照组**——例如"用 embedding 去重后，成片里同类镜头的重复率下降了多少"，
   以及**误伤率**（把不重复的镜头判成重复）。
5. **与标签的关系**：embedding 是替换 `tags` 还是并存？并存会产生**两条真相路径**（见 §2.3 的反面教训）。
6. **成本**：embedding 的推理成本 vs 本项目"人看拼图"的实际耗时——**本次没有测过这个对比**。

**在拿到第 4 条（判据与对照组）之前，不要把一个未实测的检索方式写进流程。**

---

## 9. 未核实清单（不要当事实用）

1. **embedding 的一切**：本项目**没有使用**；§8.2 的场景、§8.3 的问题全部 **未核实、未实测**。
   任何"embedding 能提升检索/去重效果"的说法在本项目里**没有证据**。
2. **记录值 64.4 km / 4984 m 的确切参数**：能确定的是"它属于 GPX 自算口径、覆盖 8 个拍摄日"，
   与库内现值（132.9 km / 39,228 m 裸累加）**不是同一套规则**；
   当年那套规则的具体阈值/平滑参数**没核到**。
3. **照片校验的具体实现细节**：偏差分布（`max 11.75 m / mean 1.45 m / ≤10 m 32/34`）是本文
   独立复算的；但**当时那次校验的脚本与代码没有留存**，
   而且过程中出现过**"把本地时间当 UTC 对齐"的时区错**（后来修正）——
   所以记录值"0.00–0.01 km"只能视为**量级正确**，精确到 mm 的说法不成立。
4. **外部权威口径本身的来源**是"一次路线校准的记录"，不是本库的一部分；
   本文只能引用它，**无法在此库内独立复算**（房间/外部记录未附 GPS 附件、未附照片）。
5. **`cum_dist_km` 是否为徒步累计**：源码（只累加徒步段）与库内分布
   （车行行的值在 0.19–10.58 km、且逐日最大值都小于当天 `walk_km`）两条证据一致，
   **判定为徒步累计**；但没有找到"当初就这么设计的"文字说明，
   **意图未核实**（有可能是命名事故）。
6. **`sheets.status`/`assignee`、`days.weather`/`highlights`、`edit_meta`、`audio_stats.note`/`noise_floor_db`
   这些列"是设计后放弃还是写了没用"——未核实**；本文只报告它们**实测没被填**。
7. **`review_frames` 抽帧位置（t_sec 从 0.1 到 188.22 s）**的抽样规则（是否 6%/50%/90%）
   在库里查不到，**未核实**；但 453 = 151×3 说明"每条 3 帧"是硬纪律。
8. **`edit_plan` 里 27 行无 `asset_id` 的语义**（标题卡/黑场/文字卡）**未核实**，
   只能确定它们不对应素材。
9. **轨迹点的时间戳精度**：`t_epoch` 是整数秒，实测相邻点间隔存在 1 s 与 2 s 交替与
   单点 23 分钟以上的天数边界（有一天的轨迹从 `23:59:59` 断到次日 `00:00:00`），
   跨天/跨段匹配的边界行为**未系统验证**。
10. **本文所有数值都是那一次素材的实测值**（151 条 / 8 天 / 55.11 GiB / 297,761 个轨迹点……）。
    换素材必须重新量基线；**可复用的是判据、阈值怎么定、怎么验证**。

---

## 10. 复算方式

```powershell
# 只读连接（绝不写库）：URI 里加 mode=ro
#   sqlite3.connect("file:<path>/medialib.db?mode=ro", uri=True)

# 表/视图/列/索引一览（库里自带查询助手）
python tools/dbq.py --schema

# 覆盖率与对账（模板）
SELECT (SELECT COUNT(*) FROM assets) assets,
       (SELECT COUNT(*) FROM analyses) analyses,
       (SELECT COUNT(*) FROM asset_geo) asset_geo,
       (SELECT COUNT(*) FROM audio_stats) audio_stats,
       (SELECT COUNT(*) FROM review_frames) review_frames,
       (SELECT COUNT(*) FROM gpx_points) gpx_points;

# 匹配质量必查清单
SELECT a.asset_no, a.day, g.match_quality, g.dt_sec
  FROM asset_geo g JOIN assets a ON a.id=g.asset_id
 WHERE g.match_quality IN ('far','none') OR g.dt_sec > 60 ORDER BY g.dt_sec DESC;

# 徒步/车行/爬升（逐日 + 合计）
SELECT day, track_km, walk_km, drive_km, ascent_m, walk_ascent_m, max_speed_kmh
  FROM day_metrics ORDER BY day;
SELECT SUM(track_km), SUM(walk_km), SUM(drive_km), SUM(ascent_m) FROM day_metrics;

# 时间线（务必带 variant）
SELECT variant, COUNT(*), MIN(position), MAX(position) FROM edit_plan GROUP BY variant;
```

**照片偏差复算的最小骨架**（依赖：照片 EXIF GPS + 拍摄时刻、库里的 `gpx_points`）：

```python
# 1) 照片 EXIF：DateTimeOriginal（本地时间，需补时区）+ GPSLat/Lon
# 2) 按照片日期取当天轨迹：SELECT t_epoch,lat,lon FROM gpx_points WHERE track_id=?
#    ORDER BY t_epoch     （track 与日期的对应关系存在 gpx_tracks.name）
# 3) 用拍摄时刻（转 epoch）二分找最近时刻点，算 haversine 水平距离
# 4) 报 max / mean / ≤10m 占比 / 逐日最大值——四个数一起报，缺一个都会误判
```

**指标口径敏感度复算**：固定同一批轨迹点，只改
（a）跳点阈值（200 km/h）、（b）徒步速度阈值（2.0/3.0/4.0 m/s）、
（c）海拔平滑窗与最小步长阈值（如 平滑 5+≥3 m / 平滑 11+≥5 m），
把每个组合的总量列成一张表。**只要这张表里最大值与最小值差 >10%，
就必须在文档里写明用的是哪一列。**
