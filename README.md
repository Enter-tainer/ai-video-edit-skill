# ai-video-edit-skill

**把一堆原始视频素材 + 一个模糊的创作意图，做成一支能发布的成片。**

这是一份**给 agent 看的操作手册**（不是给领导看的汇报）。
它来自一次真实项目的复盘：151 段手持运动相机素材（71.6 分钟 / 55 GB）
剪成 2:34 / 2:55 / 5:08 三个版本，迭代了十几轮。
手册把那次迭代里**每一条踩过的坑**写成了"**规则 / 为什么 / 怎么验证**"，
并配上一套**可复算的量化验收工具**。

解决的问题很具体：**素材是"过程记录型"（手持 POV、边走边拍、没有机位设计）时，
能不能剪好取决于敢不敢扔**——而"扔"这件事最容易出错的地方有两个：
**AI 评分替你做审美判断**，以及**渲染/拼接/字体/音频的静默错误**。
手册对这两类都给了可执行的判据和检查方法。

---

## 怎么用

| 你的情况 | 从哪开始 |
|---|---|
| 第一次做这类片子 | 从 [`SKILL.md`](SKILL.md) 读起，按 §2 的九步流水线走 |
| 已经在剪，想查某个坑 | 直接看 [`SKILL.md`](SKILL.md) §7「失败模式清单」（53 条症状→根因→修法） |
| 要写校验脚本 | [`references/acceptance-metrics.md`](references/acceptance-metrics.md)（算法 + 阈值怎么定 + 复算命令） |
| ffmpeg 报奇怪的错 | [`references/ffmpeg-pitfalls.md`](references/ffmpeg-pitfalls.md) |
| 要挑素材 / 定节奏 | [`references/selection-and-structure.md`](references/selection-and-structure.md) |
| 要拆解对标视频 | [`references/benchmark-breakdown.md`](references/benchmark-breakdown.md)（量什么、怎么判、怎么映射成改刀与补拍清单） |
| 配乐 / 扒谱 / 生成 | [`references/music-and-score.md`](references/music-and-score.md)（对标拆解→配方→ABC→回读验收） |
| 设计素材库 / 用 GPS | [`references/data-geo-schema.md`](references/data-geo-schema.md)（schema、轨迹口径、位置校验） |
| 要多人/多 agent 协作 | [`SKILL.md`](SKILL.md) §8 + [`references/agent-orchestration.md`](references/agent-orchestration.md) |
| 想用现成脚本 | [`scripts/README.md`](scripts/README.md)（先改 `mlib.py` 的配置） |

**最小可用路径**（只有这些也够干活）：

1. 入库时**记下数据坑**（时区、时间格式）；
2. 自动审片只当**初筛**，凡要进片的镜头**必须抽帧拼联系表人眼过一遍**；
3. 选片结论里必须有一条 `seen`（**只有看过帧才说得出的细节**）——它是唯一能被独立复核的证据；
4. 缓存键必须包含**所有**影响输出的参数（含音频增益、时长、裁切，以及一个手动的画面版本号）；
5. 拼接后**必须校验总时长**（坏分段会让拼接静默丢时间）；
6. 交付前跑三个硬检查：**解码 0 错误**、**镜长中位符合版本梯度**、**成片音频电平在预期区间**。

---

## 目录

```
README.md                              ← 本文件
SKILL.md                               ← 主体：何时用、九步流水线、选片/结构原则、
                                          23 条技术硬规则、量化验收、53 条失败模式、
                                          9 条元规则、什么时候该用 agent team、未核实清单
references/
  ffmpeg-pitfalls.md                   ffmpeg / 滤镜链坑全集（症状→根因→修法→怎么验证）
  acceptance-metrics.md                量化指标：怎么算、阈值怎么定、怎么复算
  selection-and-structure.md           选片判据、结构详略预算、一次完整迭代的形态
  agent-orchestration.md               多 agent 协作：什么时候派、怎么分工、怎么复核、中断恢复
  music-and-score.md                   配乐：对标拆解定配方、手写 ABC 生成、纯器乐双证据、铺床余量
  data-geo-schema.md                   素材库 schema、GPS 轨迹与口径、位置校验、embedding（已实测）
  provenance.md                        结论的来源类型与核实状态（哪些没核实）
scripts/
  README.md                            关键验收工具清单 + 换项目要改什么
  contact.py / day_inventory.py        抽帧拼联系表 / 按天盘点（选片用）
  shot_stats.py / seg_audit.py         镜长验收 / 逐段时长核对
  amb_audit.py / av_diag.py            原声分档（水/风能量比）
  sharp_check.py / shake_rank2.py      锐度隔离测试 / 相位相关抖动排序
  mlib.py                              公共库（路径、ffprobe、SQLite 连接）
  unzstd.js / sess_recover.py          把中断的并行任务的结论从会话记录里捞回来
  embed_index.py / embed_search.py     多模态索引与检索（自然语言找素材 / 用照片找最像的镜头 / 找近重复）
```

---

## 两条使用约定

1. **数字不要照搬**。手册里的中位镜长、比例、dB、百分比都是那次素材的实测值；
   换素材要**重新量基线**。可复用的是**判据、阈值怎么定（找分布空档）、怎么验证**。
2. **凡标"未核实"的不要当事实用**。清单在 [`SKILL.md`](SKILL.md) §9 与
   [`references/provenance.md`](references/provenance.md) §四。
   其中两条值得特别注意：一个流传的「锐度提升 12~22%」**只出现在一次汇报文本里、没有复算记录**
   （可复算的是 69%→75%）；有两处文档明确落后于工具源码（**以源码为准**）。
