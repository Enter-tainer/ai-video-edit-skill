# ffmpeg / 滤镜链坑全集

> 每条都是**实测踩过**的。格式：症状 → 根因 → 修法 → 怎么验证。
> 权威来源是**工具源码**（渲染主程序与分镜生成脚本），文档在个别地方落后于代码，已标注。

---

## 1. 滤镜顺序

### 1.1 `vidstabtransform` 必须在 `fps` 之前 ⭐

**症状**：稳定化之后画面**闪烁 / 比不稳定的还抖**。

**根因**：`trf` 是按**源素材的帧率**逐帧生成的（这批运动相机是 59.94fps），
`vidstabtransform` 每处理一帧就顺序消费一条 trf。
放在 `fps=30` 之后 → 每输出一帧只消费半条 trf 的时间跨度 →
**修正量整体提前一半**，抖动相位错了位。

**修法**：

```
vidstabtransform=… → crop → scale=W:H:flags=lanczos → fps=30 → setsar=1 → 浮层
```

**验证**：交换顺序渲同样 3 秒做抽帧 A/B；或对同一窗口跑相位相关抖动（`shake_rank2.py`）——
错误顺序的 shake_px 不会更小。

### 1.2 稳定化必须在 `scale` 之前（源分辨率）⭐

**症状**：全片发**糊**。

**根因**：链路里三次重采样：裁切 → 缩放 1080 → **稳定化逐帧重采样** → 编码。
在 1080p 上做逐帧重采样，等于在低分辨率上再插值一次；
放在 4K 做，后面那次 lanczos 缩小会把变换的重采样误差**平均掉**。

**实测**（拉普拉斯方差，以"源 4K→1080"为 100%）：

| 配置 | 相对锐度 |
|---|---|
| 只裁不缩（参考） | 94% |
| `crop → scale(1080) → vidstab`（旧） | **69%** |
| `crop → vidstab(4K) → scale(1080)`（现在） | **75%** |

**结论**：**"糊"的主因不是 1080p 输出，而是在 1080p 上做逐帧重采样。**

**验证**：`scripts/sharp_check.py <素材号> <入点>` 一次跑 5 个用例。

> ⚠️ **文档漂移**：`剪辑方案.md` §13.4 说 "`vidstabtransform` 直接接在 `scale` 之后"
> （v16 时点），代码现状是在 `scale` **之前**。以代码为准。

### 1.3 裁切与缩放必须在同一条链上按需二选一

**规则**：

```python
geo = f"scale={W}:{H}:flags=lanczos"
if r.get("crop_bottom"):                    # 车拍：只裁底部
    b = float(r["crop_bottom"])
    geo = (f"crop=ih*{1-b:.4f}*16/9:ih*{1-b:.4f}:"
           f"(iw-ih*{1-b:.4f}*16/9)/2:0,scale={W}:{H}:flags=lanczos")
elif r.get("zoom"):                         # 通用轻裁 / 个别镜头的大裁
    z, yo = float(r["zoom"]), float(r.get("zoom_y", 0.5))
    geo = (f"crop=iw/{z}:ih/{z}:(iw-iw/{z})/2:(ih-ih/{z})*{yo},"
           f"scale={W}:{H}:flags=lanczos")
```

**注意**：分镜生成侧会给车拍镜头**同时**设 `zoom` 和 `crop_bottom`，
但渲染侧是 `elif` → **`crop_bottom` 优先**，两者**不叠加**。改这段代码时不要改成 `if`。

---

## 2. 滤镜参数解析

### 2.1 Windows 盘符的冒号会被当成选项分隔符 ⭐

**症状**：trf 生成到奇怪的地方 / `result=C` 之类的截断 / 找不到文件。

**根因**：ffmpeg 的滤镜参数解析器用 `:` 分隔选项，
所以形如 `result=<盘符>:\<目录>\t.trf` 的写法会被从盘符的冒号处拆断（报错里常常只剩 `C`）。

**修法**：

```python
subprocess.run([... , "-vf", f"…vidstabdetect=…:result={name}"], cwd=STAB_DIR)
# name 是相对文件名；STAB_DIR = <trf 运动文件目录>
# 但分段输出路径必须是绝对路径（output 不走滤镜参数解析）
```

**验证**：故意传一次绝对路径看报错；`ls` 确认 trf 落在 trf 目录下。

### 2.2 `drawtext` 里的特殊字符要转义

`text=` 里出现的 `:` `,` `[` `]` 都要转义（`\\:` `\\,` `(` `)`）：

```python
def esc(t):
    return (t.replace("\\", "").replace("'", "").replace(":", "\\:")
             .replace(",", "\\,").replace("[", "(").replace("]", ")"))
```

### 2.3 `fileformat=text` 不存在，文本模式叫 `ascii`

**症状**：`Unable to parse option value "text"`。

**修法**：写 `fileformat=ascii`；不过 **默认的二进制 trf 更好**（体积小、精度够），
这次全程用默认。

### 2.4 `interpol` 用数字，不用名字

`interpol=bicubic` 这种名字不成立，要写 `interpol=1`。
**实测 `interpol=1`(bicubic) 比 lanczos 更锐，不要换掉。**

### 2.5 `optzoom=1` 会让画面"呼吸"

- `optzoom=1`：**逐帧**算最优放大 → 缩放系数随帧变化 → 观感是"一下一下地跳"。
- `optzoom=2`：整段算**一个固定**放大系数 → 边缘不跳。**用 2。**

### 2.6 本机 ffmpeg 的 `vidstabtransform` 没有 `unsharp`

带上 `unsharp=…` 会 `Option not found` 并且**整条渲染失败**（不是"忽略这个选项"）。
想补锐化就在别处加，或者接受现状。

> ⚠️ **文档漂移**：§13.4 记录 v16 时用的是 `optzoom=1:interpol=bicubic`。
> 代码现状是 `optzoom=2:interpol=1`。以代码为准。

### 2.7 `vidstabdetect` 的 trf 必须在"与渲染完全一样的窗口"上生成

trf 是**按帧号索引**的。拿整条素材的 trf（从 0 开始）去配 `-ss` 之后的画面，会整体错位。

```python
subprocess.run([FFMPEG, "-v","error","-y", "-ss", f"{tin:.2f}", "-t", f"{d:.2f}",
                "-i", path, "-an", "-vf",
                f"scale=1280:-2,vidstabdetect=shakiness=10:accuracy=15:result={name}",
                "-f", "null", "-"], cwd=STAB_DIR, check=True)
```

detect 在 1280 宽上跑（快），transform 在源分辨率上跑（锐）——
trf 存的是**相对量**，所以在什么分辨率上 detect 不影响正确性。

按段缓存（文件名由 `seg_key` 派生）→ 重渲不用再付 detect 的代价；
删掉 trf 只会让 detect 重跑，**不影响正确性**。

---

## 3. 图形与文字

### 3.1 `drawbox` 的 `h` / `w` 是**盒子自身**的尺寸 ⭐

**症状**：给标题托底的压条跑到了**画面上半部**（天空被压暗 30%，标题却不托底）。

**根因（两层，第二层才是真正的原因）**：

1. 在 y 表达式里，`h` 指 box **自己**的高度（不是输入高度）。
2. 更隐蔽的是**求值顺序**：`drawbox` 的表达式按 **`x → y → w → h`** 求值 ——
   所以算 `y` 的时候，`h` **还没被赋值**（默认 0）。

于是：

```
drawbox=x=0:y=h-620:h=620      # y 求值时 h 还是 0 → y = -620 → 被 clamp 到 0 → 压条从顶部落下
```

**修法**：纵向定位直接用**绝对像素**（滤镜在 `scale` 之后执行，画面就是 `W×H`）：

```python
vf.append(f"drawbox=x=0:y={H - top*SCALE + k*band}:w=iw:h={band}:"
          f"color=black@{alpha:.4f}:t=fill")
```

> ⚠️ **同一个 `h`，在不同滤镜里含义不同**：
> - `drawbox` 的 `h` = **盒子高度**（且 `y` 早于 `h` 求值）；
> - `drawtext` 的 `h` = **输入高度**（所以同一段代码里 `drawtext` 的 `h-400` 是对的、
>   `drawbox` 的 `h-620` 是错的）。
> **这种"同名不同义"是 ffmpeg 最容易骗人的地方**——迁移写法的时候必须逐个查变量表。

**验证**：抽帧算**逐行平均亮度**，找单行最大跳变。
实测 bug 现场：**y=620 处有 +26/+27 的阶跃**（左右半幅同一行），
而设计位置在 y=460 处没有跳变 → 一眼定位。

### 3.2 等透明度的大压条 = 一道能看见的横向色阶

**症状**：亮天空/雪山斜坡上"上半部分和下半部分颜色不一样"。

**修法**：**31 级阶梯渐变**，自上而下 alpha 线性增长：

```python
top, bands = 620, 31
band = max(1, (top * SCALE) // bands)
for k in range(bands):
    alpha = 0.34 * (k + 1) / bands
    vf.append(f"drawbox=x=0:y={H - top*SCALE + k*band}:w=iw:h={band}:"
              f"color=black@{alpha:.4f}:t=fill")
```

早先只分 5 段（每段 6% 不透明度），**步进本身还是看得见**；31 段（每段约 15px / 约 1%）才行。
同时把顶边**下移到 620px**，让起点落在画面下部的草甸里，而不是横切山脊。

**验证**：抽帧看天空过渡是否连续、无接缝；逐行亮度剖面应该平滑。

### 3.3 字体：`fontfile` + 相对路径 = 定时炸弹 ⭐

**症状**（**有欺骗性**）：标题与数据浮层的中文是方块，
而**章节字幕与片尾滚屏却是好的** —— 同一份代码、同一台机器。

**根因**：`CJK = "msyhbd.ttc"` 是**相对路径**，而稳定化分段把进程 `cwd` 设成了 trf 目录：

| 渲染分支 | 有没有挂 `cwd=STAB_DIR` | 结果 |
|---|---|---|
| `render_video_seg`（标题、数据浮层） | **有** | 找不到字体 → **豆腐块** |
| `render_photo_seg` / `render_card_seg`（章节字幕、滚屏） | 没有 | 正常 |

**修法**：改用 **fontconfig 家族名**：

```python
CJK      = "Source Han Sans SC Heavy"    # 标题、数据浮层（大字号，要够重）
CJK_TEXT = "Source Han Sans SC Medium"   # 章节字幕、片尾滚屏（小字号）
```

好处：**与 cwd 无关**，而且能指名具体字重。

### 3.4 中文字体族

- **思源黑体 Source Han Sans 是 SIL OFL，可商用；微软雅黑（msyh）是商业字体，不能分发/商用。**
- `SourceHanSans.ttc` 是**字体集合（45 个面）**，`fontfile` 只能拿到**第一个面**
  （ExtraLight/Regular）→ 标题明显偏细。
- `drawtext` **没有 face index**，也**不支持 `fontstyle`**（`fontstyle=Bold` → `Option not found`）。
- 思源把**每个字重注册成独立家族名**：`… Medium` / `… Heavy` 可用；
  **`Source Han Sans SC Bold` 不是家族名** → tofu（实测片名整行变方块）。
- `SourceHanSansJP-Bold.otf` 也不行：**JP 子集缺某些简体字** → 方块。

**验证**：`fc-list | findstr "Source Han"` 列家族名；
渲染一帧含片名（含简体专名）的镜头，人眼确认无方块。

---

## 4. 音频

### 4.1 `concat -c copy` 在"有的段有音轨、有的段没有"时会缩短音频 ⭐

**症状**：配乐 / 原声整体**提前**；音频比画面短 **11.2 秒**（正好等于三条默片插入镜的总长）。

**根因**：没音轨的那段被按 **0 秒音频**接进去。

**修法**：

```python
if not has_audio(path):                      # ffprobe -select_streams a
    cmd += ["-f","lavfi","-t",f"{d:.2f}",
            "-i","anullsrc=channel_layout=stereo:sample_rate=48000"]
    …
    cmd += ["-map","0:v","-map","1:a","-shortest"]
```

**实测**：音频帧数 `13423`(=286.4s) → `13952`(=297.6s)。

**验证**：`ffprobe -select_streams a` 逐段查；拼完后比较音视频时长。

### 4.2 原声电平必须在**滤波之后**量，并且先过噪声门

```python
AMBIENCE_FILTER = "highpass=f=140,highpass=f=140,lowpass=f=12000"   # −24dB/oct 两级 + 12k 低通
amb_mean = mean_db(raw, af=AMBIENCE_FILTER + ",agate=threshold=-55dB")
target   = 配乐床 mean − AMBIENCE_OFFSET_DB(9)
amb_gain = clamp(target − amb_mean, -6, +34)
```

**为什么**：
- 不滤波：这批运动相机的原声 90%+ 能量在 150Hz 以下，混进来只是"隆隆声"，还把配乐糊掉。
- **必须量滤波之后**：否则差 20dB 以上。
- **必须先过噪声门**：逐镜原声里大部分被压到 −70dB，直接量总线均值会被静音段拖低十几 dB，
  反推出的增益会把剩下几个"有水声"的镜头**推爆**。
- 固定值（`volume=-25dB`）比 −18dBFS 的配乐床低 23dB → **根本听不见**。

### 4.3 混音末端

```
amix=inputs=N:duration=first:normalize=0 → volume=-2dB → alimiter=limit=0.94
```

`normalize=0` 很重要：默认 `amix` 会按输入数归一，把已经量好的电平关系打乱。

---

## 5. 拼接与缓存

### 5.1 `concat -c copy` 遇到坏分段会**静默跳过** ⭐

**症状**：成片比计划**少 12.4 秒**，**不报任何错**；而且分段级缓存还把那个坏文件当"已缓存"继续用。

**根因**：上一次渲染被 kill，分段写了一半、没有 moov atom。

**修法**（渲染脚本里内建断言）：

```python
lst = 写 list.txt（绝对路径，反斜杠换成正斜杠）
subprocess.run([FFMPEG,"-v","error","-y","-f","concat","-safe","0","-i",lst,"-c","copy",raw], check=True)
got = probe_dur(raw)
if got is not None and abs(got - t) > 0.35:
    bad = [p for p in parts if (probe_dur(p) or 0) < 0.05]
    raise SystemExit(f"拼接后时长对不上：分镜表 {t:.1f}s，实际 {got:.1f}s…可疑分段 {bad}")
```

**验证**：断言本身就是验证；另跑 `seg_audit.py` 做逐行核对（Δ > 0.25s 报警）。

### 5.2 分段缓存文件的命名

见 SKILL.md T1。核心：**文件名 = (素材/照片/卡片/文件)+入出点 + 所有影响输出的参数的短哈希**。

必须进哈希的字段（都是踩过才加的）：

| 字段 | 漏了会怎样 |
|---|---|
| `tin` / `tout` | `--only` 时不同窗口算出同名文件互相覆盖 → 整片多 10.5s |
| `ov` / `sub` | 改花字/字幕文案不失效 → 重渲还是旧字 |
| `scrim` / `zoom` / `zoom_y` / `lines` | 改压条/裁切/滚屏文案不失效 |
| `stab` / `crop_bottom` | 开关稳定化/裁底后命中旧画面 |
| `amb_db` | 改原声清单不失效 → 声音还是老的（差 48dB） |
| `dur` | `card` 的 base 不含时长，4.0s 与 5.0s 的两版互相顶 |
| `v` = `LOOK_VER` | 改字体/描边/渐变这类"不在行字段里"的画面参数后，拿到旧画面 |

**验证**：改任意受控参数 → 重渲 → 文件名必须变。名字没变就是键漏了。

---

## 6. 编码

| 用途 | 编码 | 参数 |
|---|---|---|
| 1080p 分享版 | H.264 NVENC | `-preset p5 -rc vbr -cq 21 -b:v 16M -maxrate 24M -pix_fmt yuv420p` |
| 4K 母版 | HEVC NVENC **10bit** | `-cq 23 -b:v 40M -maxrate 55M -pix_fmt p010le -tag:v hvc1` |
| 音频 | AAC-LC 192kbps / 48kHz 立体声 | — |
| 分段中间文件 | 与最终一致（**不要用低码率中间文件**，否则多一代压缩白掉画质） | — |

- **稳定化不要预生成"稳定化中间素材"**：会多一代压缩、4K 母版跟着掉画质；
  在分段里做只多一遍 `vidstabdetect`。
- 拼接用 `-c copy`（不重编码），最终混音时视频也是 `-c:v copy` + `-movflags +faststart`。
- 渲染倍率：`RENDER_SCALE=2` 出 4K，字号/位移/边距**同比放大**（写一个 `sy()` 处理 `"h-120"` 这类定位）。
- **编码参数（分辨率/色深/码率/质量档）不在镜头缓存键里**：这次靠
  "1080p 与 4K 用**不同的缓存目录**"来规避。**遗留风险**：改了质量档（CQ）会复用旧分段。
  要么把编码参数也进键，要么把质量档写进目录名。

---

## 7. 其他实测踩到的（不一定是 ffmpeg 的锅，但都发生在渲染链上）

### 7.1 同一路输入不能在滤镜图里直接用两次

**症状**：照片段的滤镜图报错。
**根因**：filtergraph 里同一个输入流被引用两次。
**修法**：先 `split` 成两路再分别处理。

### 7.2 `filter_complex` 末尾要有输出标签

**症状**：`filter_complex` 解析失败。
**修法**：链路末尾显式打 `[v]`（或对应标签），并 `-map "[v]"`。

### 7.3 输出路径 == 输入路径

**症状**：渲染器"把文件复制到自己身上"，跑完什么都没变（甚至毁掉输入）。
**修法**：渲染前断言 `os.path.abspath(out) != os.path.abspath(src)`。

### 7.4 多规格必须各自跑通 ⭐

**症状**：1080p 两条渲染全挂，而 4K 完全正常。
**根因**：编码器名传成了 `h264` 而不是 `h264_nvenc` ——
而**另一档走的判断分支会把它映射成 `hevc_nvenc`，所以没暴露**。
**教训**：**每一档输出（分辨率 × 色深 × 帧率）都要各自实跑一次**，
不能"验了一条就认为链路通了"。

### 7.5 静默 `catch` 会吞掉"素材找不到"

**症状**：渲染"成功"，成片里没有音乐。
**根因**：配乐文件用**相对路径**加载，进程 `cwd` 不对 → 找不到文件，
而**异常被静默捕获了**。
**修法**：路径改绝对；**不要静默 catch**同类错误（M6）。

### 7.6 大核卷积慢到不可用

**症状**：几十亿次乘法的滑动统计把一步操作拖到不可接受。
**修法**：改成**累积和**（前缀和）实现滑窗统计。
**教训**：这个坑**踩了两次**——第一次改完没沉淀成可复用函数（M9）。

### 7.7 `unsharp` / `fontstyle` 这类选项"有没有"取决于 build

用任何滤镜选项之前先 `ffmpeg -filters` / `-h filter=<name>` 探一遍；
换个 ffmpeg build 就得重新确认。实测这个 build 缺 `vidstabtransform` 的 `unsharp`
和 `drawtext` 的 `fontstyle`，带上就直接失败，**不是"忽略"**。

### 7.8 源帧率不是整数倍时用 `setpts` 改时间戳

25p → 30fps（**1.2×**）用 `setpts=PTS/1.2`（帧数守恒，不补帧不丢帧），
**先转好存成中间文件**再入片。不要指望防抖/稳定化工具帮转帧率。
竖拍（`rotation=90`）在横屏里只能用一半像素。
