# scripts/：可复用的验收集

这些脚本来自一次真实项目的工具集，**按可复用目的做过最小改造**：
只把写死的项目路径 / 素材编号换成了占位符与环境变量，**逻辑没动**。

> ⚠️ **不是开箱即用**：大多数脚本依赖 `mlib.py`，需要先按你的项目改配置。

---

## 一、先改 `mlib.py`

```python
# 可用环境变量覆盖，方便多项目复用
ROOT = os.environ.get("EDIT_ROOT", r"<项目根目录>")
SRC  = os.environ.get("EDIT_SRC",  r"<原始素材目录>")
FONT     = os.environ.get("EDIT_FONT",     r"<拉丁字体文件>")   # PIL 直读用
CJK_FONT = os.environ.get("EDIT_CJK_FONT", r"<中文字体文件>")   # 只给 PIL 用
DAYS     = os.environ.get("EDIT_DAYS", "").split(",")          # 覆盖的拍摄日 YYYYMMDD
```

还要确认：`ffmpeg` / `ffprobe` 在 `PATH` 里；
这些脚本读的 json 是**本手册假定的分镜表结构**
（`{"rows": [{"no","tin","tout","seg","type","dur","photo","card",…}]}`），
换项目时要对上你自己的结构。

**中文字体注意**：`CJK_FONT` 只给 PIL 直读的场景用；
**用 ffmpeg 的 `drawtext` 时请用 fontconfig 家族名**（见 SKILL.md T8/T9），不要用文件路径。

---

## 二、脚本清单

| 脚本 | 作用 | 依赖 | 换项目要改什么 |
|---|---|---|---|
| `mlib.py` | 公共库：路径常量、`ffprobe` 封装、SQLite 连接（只读/可写、WAL、`busy_timeout`）、时间工具 | — | **必须先改**（见上） |
| `contact.py` | ⭐ **抽帧拼联系表**（选片核心工具）：每条素材均匀抽 N 帧，行首标素材号/拍摄时间/时长，每格标帧时间点 | `mlib`、`PIL` | `assets` 表的 `path/duration_s/shot_at_local` 字段；标签字体文件 |
| `day_inventory.py` | 列某天的全部素材（编号/时间/时长/评分/角色/场景/issues/摘要），用于"分日重挑" | `mlib` | `assets` / `analyses` 表结构 |
| `shot_stats.py` | ⭐ **镜长验收**：各版本镜长的中位/平均/≥8s 数，**开场与正文分开** | `mlib` | 顶部的分镜表文件名列表；`seg` 前缀（`开场` / `第`） |
| `amb_audit.py` | ⭐ **原声分档**：按 `(500–8000Hz)/(<200Hz)` 能量比给每条**实际使用的窗口**打分，输出"留声清单"建议 | `mlib`、`av_diag` | 顶部的分镜表文件名列表 |
| `av_diag.py` | 底层判据：`shake_score()`（帧间差分 RMS）+ `amb_class()`（水/风能量比）；被 `amb_audit.py` 引用 | `mlib`、`numpy` | 无（纯算法） |
| `seg_audit.py` | ⭐ **逐段时长核对**：分镜表"应有秒数" vs 分段文件"实际秒数"，Δ>0.25s 报警 | `mlib`、渲染主程序的 `seg_key`/工作目录 | 它 import 渲染主程序 → 要么改 import，要么把那两个常量抄进来 |
| `sharp_check.py` | ⭐ **锐度隔离测试**：一次跑 5 个配置（不裁不稳 / 旧顺序 / lanczos / 新顺序 / 只裁不缩），在 1080p 上比拉普拉斯方差 | `mlib`、`numpy` | 无（纯算法）；trf 工作目录。**注意其 docstring 有一句与实测结论相反，以 `references/acceptance-metrics.md` 为准** |
| `shake_rank2.py` | **相位相关抖动排序**：480×270 @30fps 逐帧估全局平移，分离高频抖动与有意运镜 | `mlib`、`numpy` | 无（纯算法） |
| `res_check.py` | ⭐ **稳定化分辨率失配体检**：同一段素材渲 **4 个版本**（不稳定化对照 / stab@输出分辨率 / stab@源分辨率 / stab@检测分辨率），逐帧相位相关（**搜索窗 ±24px 且先 `fftshift`**）算**高频残差**与平均平移 → 判定"在减震"还是"在加震"（过校正）。带 **`--selftest`** 离线自检（不需要素材库；断言"静止画面必须量出 0"） | `mlib`、`numpy` | 无（纯算法）；`RESCHK_STAB_DIR`（trf 工作目录）/ `RESCHK_TMP`（临时输出去处）/ `RESCHK_DETECT_SCALE` / `RESCHK_OUT_W`·`RESCHK_OUT_H` / `RESCHK_SEARCH` 环境变量（见下）。**注意：与原始版本相比修了两处算法 bug**（`fftshift`、位移符号），所以**旧文档里那组 12.367/12.725/… 的数复算不出来** |
| `unzstd.js` | ⭐ 解"增量追加写"的 `.zstd` 日志（**按魔数切多帧**，很多解压库只解第一帧） | Node（含 `zlib.zstdDecompressSync`） | 无（通用工具） |
| `sess_recover.py` | 从会话 `.jsonl` 里抽出助手文本（配合 `unzstd.js`，把被 kill 的 fan-out 结论捞回来） | 无（`SESS_DIR` / `NODE_BIN` / `FINAL_KEYS` 环境变量） | 记录形状 `{type,data}` 与"最终结论字段名" |
| `embed_index.py` | ⭐ **建多模态索引**：每条素材在时长上取 3 帧 embed 图片 + 用摘要 embed 文本；照片各 embed 一次。**只新增**两张表，不碰已有表；支持断点续跑 | `mlib`、`PIL`、一个 embedding 服务（`EMBED_BASE`） | `EMBED_BASE` / `EMBED_MODEL`；`mlib.py` 的库路径；照片目录；抽帧比例 `FRAME_FRACS` |
| `embed_search.py` | ⭐ **检索**：`--text` 用自然语言找素材、`--photo` 用一张照片找最像的镜头、`--similar` 找重复镜头；`--pool max` 会报出命中在第几秒 | 同上 | 同上 |
| `yue2_client.py` | **配乐服务的纯 HTTP 客户端**（写谱 `plans` / 渲染 `songs` / 扒谱 `transcribe` / 谱面工具 `inspect`·`strip-chords`·`compare` / `jobs`·`files`·`get` / `unload`）：默认**异步提交 + 轮询**，4xx/422 会把服务端 `detail` 一起抛；端到端步骤见 `references/music-and-score.md` §3.6 | 无（Python 3 标准库，不用 `mlib`）；⚠️ 它连的是**外部服务**，不是本地文件 | **服务地址**用 `YUE2_BASE` 环境变量（默认回环 `http://127.0.0.1:8100`）；鉴权 `YUE2_API_KEY`；超时 `YUE2_TIMEOUT`（默认 600s）。**模型 / 端点名**（`/v1/plans`、`/v1/songs`、`/v1/transcribe`、`/v1/tools/abc/*`、`/v1/jobs/{id}`、`/v1/admin/unload`）是服务侧契约名，换一套服务先跑 `python scripts/yue2_client.py doc` 看它的 `endpoints` 再改名；扒谱产物要加 `--via transcribe`（走 `/v1/transcribe/{id}/file/{name}`） |

⭐ = 这套流程里最值钱的几个验收/检索工具。

### 关于 `embed_*` 的两个前提

1. **需要一个 embedding 服务**（OpenAI 兼容的 `/v1/embeddings`）。默认连 `http://127.0.0.1:8087`，
   服务在别的机器上用 `EMBED_BASE=http://<host>:8087` 覆盖。**图片走 content 数组，文本必须带任务前缀**
   （检索侧 `task: search result | query: …`，文档侧 `title: … | text: …`），不带前缀排序会明显变差。
2. **它是"检索"，不是"审美判断"**。实测四个查询里，期望素材**全部只排到第 2**，被"同日同场景的邻居"反超——
   模型分得清"这是哪儿"，分不清"这条和那条差在哪"。所以它可以用来**缩小候选集**，
   不能替代抽帧看图那一步（见 `SKILL.md` §3）。索引规模与验收数字见
   `references/data-geo-schema.md` 的《附：embedding 实测》。

---

## 三、复算命令

```bash
# 选片（人眼复核）
python scripts/contact.py --out work/look.png --frames 6 <素材号> <素材号> ...
python scripts/contact.py --out work/car.png  --frames 6 --tin 4 --tout 20 <素材号> ...
python scripts/day_inventory.py <YYYY-MM-DD>

# 验收
python scripts/shot_stats.py                          # 镜长中位（正文/开场分开）
python scripts/amb_audit.py                           # 水/风比 → 留声清单
python scripts/seg_audit.py <分镜表.json>              # 逐段时长
python scripts/sharp_check.py <素材号> <入点秒>        # 锐度隔离（5 个配置）
python scripts/shake_rank2.py <素材号> <素材号> ...    # 抖动排序
python scripts/res_check.py <素材号> <入点秒> <时长秒>  # 稳定化分辨率失配（4 个版本高频残差）
python scripts/res_check.py --selftest                # 先验估计器：静止画面必须量出 0

# 中断恢复
node scripts/unzstd.js <in.zstd> <out.jsonl>
python scripts/sess_recover.py

# 多模态索引与检索（需要 embedding 服务）
python scripts/embed_index.py                 # 全量建索引（断点续跑，已建过的跳过）
python scripts/embed_index.py --only-photo    # 只补照片
python scripts/embed_search.py --text "雾气弥漫的山谷"      # 自然语言找素材
python scripts/embed_search.py --photo photos/trip/<照片>.jpg  # 用照片找最像的镜头
python scripts/embed_search.py --similar <素材号>           # 找重复/近重复镜头（成片去重）
python scripts/embed_search.py --text "..." --pool max      # 报出命中在第几秒
```

---

## 四、没有放进来的部分

代价最高、也最难通用化的是**渲染主程序**与**分镜生成脚本**本身
（缓存键、滤镜链、混音、字体、配乐床的完整实现）。
它们是本手册的核心依据，但和项目的分镜表结构、素材库强耦合，
所以这里只放验收工具。**该抄的常量与注释已经完整抄进 `SKILL.md` 与
`references/ffmpeg-pitfalls.md`**，其中：

- 缓存键的完整实现 → `SKILL.md` T1；
- 滤镜链顺序与参数 → T4 / T5 / T6 / **T6b**（帧率与 `scale`）；
- 混音与配乐床 → T12 / T13；
- 裁切参数 → T17 / T18（**整片轻裁已废弃；车拍裁底必须保留**）。

### 关于 `res_check.py` 的四个约定

1. **施加分辨率必须等于检测分辨率**（`SKILL.md` T5）。脚本的 4 个版本就是这个判据的 A/B：
   只有"施加 = 检测"那一档能**低于不做稳定化的对照**。
   > ⚠️ **这条规则成立，但"当时那组实测数"不成立**：
   > 旧版脚本的搜索窗**没做 `fftshift`**（`irfft2` 的零位移在第 0 个索引，不在画幅中心），
   > 于是**完全静止的画面也会量出 12~14 px**。本目录的版本已修，
   > 并且加了 `--selftest`（**静止画面必须量出 0**）。**用旧数得出的结论要重新测。**
2. **"近乎静止"要拆开说**。**完全静止**的镜头（四档都是 0）**没有信号**，
   **摇镜**又会被内容运动淹没（复算时摇镜上"施加 = 检测"档反而**最高**）。
   需要的是"**手持、机位大体不动、但确实有小幅残余抖动**"的窗口——这种窗口最难挑，
   也是这条方法真正的门槛。
3. **改 `shift()` 之前先跑 `--selftest`**。它断言四件事：平移估得准、静止序列 = 0、
   交替抖动 > 1、帧太少返回 `None`。
4. **全部可调项都在环境变量里**（都有默认值，不写死任何路径）：

   ```
   EDIT_ROOT            项目根目录（mlib.py 读；见上面第一节）
   RESCHK_STAB_DIR      trf 工作目录，默认 <ROOT>/roughcut/trf
   RESCHK_TMP           4 个版本的临时渲染输出去处，默认 <ROOT>/work
   RESCHK_DETECT_SCALE  vidstabdetect 的检测宽度，默认 1280
   RESCHK_OUT_W / _H    4 个版本的统一输出尺寸，默认 1920×1080
   RESCHK_SEARCH        相位相关的搜索窗半径(px)，默认 24
   RESCHK_ANALYSIS_W/_H/_FPS  分析尺度与帧率，默认 480×270 @30
   RESCHK_SMOOTHING     vidstabtransform 的 smoothing，默认 30
   ```

音乐生成、打包、音效合成这类依赖外部服务或目录约定的脚本也没有放进来。
