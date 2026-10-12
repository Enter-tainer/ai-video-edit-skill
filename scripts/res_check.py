# -*- coding: utf-8 -*-
"""查"空间在波动"：`vidstabtransform` 的修正量是不是被分辨率放大了？

`vidstabdetect` 检测出来的平移量是**检测画面上的像素**；
`vidstabtransform` 把它当成**自己输入画面上的像素**施加。
两者分辨率不一致时修正量会被按比例放大：
检测 1280 → 施加 4K（3840）= **放大 3×**；施加 1080 = **放大 1.5×**。
过校正的观感就是"画面在晃 / 空间在波动"。

做法：对**同一段素材**渲 4 个版本，逐帧用**相位相关**估全局平移
（**搜索窗限制在 ±SEARCH px，且先把零位移 `fftshift` 到画幅中心**），再看：
  · **高频残差 std**（`hf = d − movavg(d)` 的 RMS）——越大 = 越晃；
  · **平均平移**——有意运镜的速度，用来确认四个版本比的是同一段运动。

判据：**只有"施加分辨率 = 检测分辨率"那一档能同时低于"不稳定化"的对照**。
另外两档比不稳定化**还差** ⇒ 过校正 ⇒ 在加震（不是"减震不够"）。

⚠️ **先证明你量的不是噪声底**。历史上这个脚本漏了 `fftshift`：
`irfft2` 的零位移在**第 0 个索引**，不在画幅中心，直接按 `H//2` 取窗等于把窗开在
"半帧位移"处 —— 于是**完全静止的画面也会量出 12~14 px**，看上去还挺"有区分度"。
现在修好了，并且 `--selftest` 会断言"静止序列必须量出 0"。**改 shift() 之前先跑它。**

⚠️ **必须挑近乎静止的镜头**：行走/摇镜的**内容运动**会把高频残差淹没，
那种镜头只能看四个版本的**相对排序**，绝对值没有意义（复算时在摇镜上
"施加 = 检测"那一档反而最高）。

用法::

    set EDIT_ROOT=<项目根目录>              # mlib.py 读它（见 scripts/README.md）
    python scripts/res_check.py --selftest                  # 离线自检，不需要素材库
    python scripts/res_check.py <素材号> <入点秒> <时长秒>

依赖：`mlib`（`FFMPEG` / `ROOT` / `connect`）、`numpy`；
      素材库需有 `assets(asset_no, path)`。
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlib as M  # noqa: E402

# ---- 可调参数（环境变量可覆盖，默认值是实测那次的取值）----
ANALYSIS_W = int(os.environ.get("RESCHK_ANALYSIS_W", 480))   # 相位相关的分析尺度
ANALYSIS_H = int(os.environ.get("RESCHK_ANALYSIS_H", 270))
ANALYSIS_FPS = os.environ.get("RESCHK_ANALYSIS_FPS", "30")   # 只影响比较，四个版本一致即可
SEARCH = int(os.environ.get("RESCHK_SEARCH", 24))            # 搜索窗半径（px，分析尺度）
DETECT_SCALE = int(os.environ.get("RESCHK_DETECT_SCALE", 1280))  # 与渲染链的 detect 一致
OUT_W = int(os.environ.get("RESCHK_OUT_W", 1920))            # 四个版本统一到这个输出尺寸
OUT_H = int(os.environ.get("RESCHK_OUT_H", 1080))
STAB_DIR = os.environ.get("RESCHK_STAB_DIR",
                          os.path.join(M.ROOT, "roughcut", "trf"))   # trf 工作目录
TMP_DIR = os.environ.get("RESCHK_TMP", os.path.join(M.ROOT, "work"))  # 临时渲染输出去处
TRF_NAME = os.environ.get("RESCHK_TRF", "reschk.trf")
SM = os.environ.get("RESCHK_SMOOTHING", "30")


def usage() -> None:
    raise SystemExit(__doc__.strip().splitlines()[-1].strip() + "\n"
                     "（<素材号> 对应素材库 assets.asset_no）\n"
                     "离线自检（不需要素材库）：python scripts/res_check.py --selftest")


def selftest() -> None:
    """离线自检：不需要素材库，验证"位移估得准 + 静止=0 + 抖动>0"。

    这段自检是有来历的：早期版本**忘了 fftshift**，窗开在半帧处，
    结果在**完全静止**的画面上也能量出十几像素的"高频残差"。
    任何改动 `shift()` 的人都应该先跑这个。
    """
    rng = np.random.default_rng(0)
    raw = rng.normal(100, 20, (ANALYSIS_H, ANALYSIS_W)).astype(np.float32)
    F = np.fft.rfft2(raw)
    fy = np.fft.fftfreq(ANALYSIS_H)[:, None]
    fx = np.fft.rfftfreq(ANALYSIS_W)[None, :]
    F *= np.exp(-((fy ** 2 + fx ** 2) / (2 * 0.02 ** 2)))      # 要有低频结构才测得出位移
    base = np.fft.irfft2(F, s=(ANALYSIS_H, ANALYSIS_W)).astype(np.float32)

    def rolled(dy, dx):
        return np.roll(np.roll(base, int(dy), axis=0), int(dx), axis=1)

    got = shift(base, rolled(7, -5))
    assert abs(got[0] - 7) < 1e-6 and abs(got[1] + 5) < 1e-6, ("位移估错", got)
    still = analyse(np.stack([base] * 40))
    jitter = analyse(np.stack([rolled(6 if i % 2 else -6, 0) for i in range(40)]))
    assert still is not None and still[0] == 0.0, ("静止画面残差应为 0", still)
    assert jitter is not None and jitter[0] > 1.0, ("交替抖动应能量出来", jitter)
    assert analyse(np.stack([base] * 5)) is None, "帧太少应返回 None"
    print("自检通过：位移估计 = %s；静止序列高频残差 = %.3f；±6px 交替抖动 = %.3f"
          % (got, still[0], jitter[0]))


def gray_frames(path: str) -> np.ndarray:
    """把一段视频解成 (N, ANALYSIS_H, ANALYSIS_W) 的 float 灰度帧。"""
    r = subprocess.run(
        [M.FFMPEG, "-v", "error", "-i", path,
         "-vf", f"scale={ANALYSIS_W}:{ANALYSIS_H},fps={ANALYSIS_FPS}",
         "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    n = len(a) // (ANALYSIS_W * ANALYSIS_H)
    return a[: n * ANALYSIS_W * ANALYSIS_H].reshape(-1, ANALYSIS_H, ANALYSIS_W).astype(np.float32)


def shift(f1: np.ndarray, f2: np.ndarray):
    """相位相关估 f1->f2 的全局平移 (dy, dx)，峰值只在**零位移附近 ±SEARCH** 的窗口里找。

    ⚠️ 关键一步是 `fftshift`：`irfft2` 出来的**零位移在第 0 个索引**，
    不在画幅中心。不 fftshift 就直接从 `H//2` 取窗，窗其实落在"半帧位移"处，
    量到的是噪声峰（静止画面也会给出十几像素的假位移）。
    """
    F1 = np.fft.rfft2(f1 - f1.mean())
    F2 = np.fft.rfft2(f2 - f2.mean())
    R = F2 * np.conj(F1)          # 这个次序给出的峰 = f1→f2 的位移（不是反的）
    R /= np.abs(R) + 1e-9
    c = np.fft.fftshift(np.fft.irfft2(R, s=(ANALYSIS_H, ANALYSIS_W)))
    cy, cx = ANALYSIS_H // 2, ANALYSIS_W // 2
    win = c[cy - SEARCH:cy + SEARCH + 1, cx - SEARCH:cx + SEARCH + 1]
    iy, ix = np.unravel_index(np.argmax(win), win.shape)
    return float(iy - SEARCH), float(ix - SEARCH)


def analyse(a: np.ndarray):
    """返回 (高频残差 px, 平均平移 px)；帧太少返回 None。"""
    if len(a) < 8:
        return None
    d = np.array([shift(a[i], a[i + 1]) for i in range(len(a) - 1)])
    k = np.ones(11) / 11                      # 11 帧滑窗 ≈ 高频/低频的分界
    hf = np.stack([d[:, 0] - np.convolve(d[:, 0], k, "same"),
                   d[:, 1] - np.convolve(d[:, 1], k, "same")], axis=1)
    return float(np.sqrt((hf ** 2).mean())), float(np.hypot(d[:, 0].mean(), d[:, 1].mean()))


def main() -> None:
    if "--selftest" in sys.argv:
        selftest()
        return
    if len(sys.argv) < 4:
        usage()
    clip, tin, dur = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])

    con = M.connect(readonly=True)
    row = con.execute("SELECT path FROM assets WHERE asset_no=?", (clip,)).fetchone()
    if not row:
        raise SystemExit(f"素材库里找不到 {clip}")
    src = row["path"]

    os.makedirs(STAB_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)

    # trf 必须在**和渲染完全一样的窗口**上检测（trf 按帧号索引）。
    # 文件名走相对路径 + cwd=STAB_DIR：Windows 盘符的冒号会被 ffmpeg 的滤镜参数解析器拆断。
    subprocess.run(
        [M.FFMPEG, "-v", "error", "-y", "-ss", f"{tin:.2f}", "-t", f"{dur:.2f}", "-i", src, "-an",
         "-vf", f"scale={DETECT_SCALE}:-2,vidstabdetect=shakiness=10:accuracy=15:result={TRF_NAME}",
         "-f", "null", "-"], cwd=STAB_DIR, check=True)

    V = f"vidstabtransform=input={TRF_NAME}:smoothing={SM}:optzoom=2:interpol=1"
    geo_out = f"scale={OUT_W}:{OUT_H}:flags=lanczos"
    geo_det = f"scale={DETECT_SCALE}:-2"
    cases = [
        ("不稳定化（对照）",
         f"{geo_out}"),
        (f"stab@{OUT_W}（施加≠检测，错）",
         f"{geo_out},{V}"),
        ("stab@源分辨率（施加≠检测，错）",
         f"{V},{geo_out}"),
        (f"stab@{DETECT_SCALE}（施加=检测，对）",
         f"{geo_det},{V},{geo_out}"),
    ]

    print(f"素材 {clip}  @{tin:.1f}s +{dur:.1f}s   检测宽 {DETECT_SCALE}   搜索窗 ±{SEARCH}px\n")
    print("%-40s %14s %14s" % ("", "高频残差px", "平均平移px"))
    for i, (tag, vf) in enumerate(cases):
        p = os.path.join(TMP_DIR, f"reschk_{i}.mp4")     # 用序号，不用 hash()（跨进程不稳定）
        subprocess.run(
            [M.FFMPEG, "-v", "error", "-y", "-ss", f"{tin:.2f}", "-t", f"{dur:.2f}", "-i", src,
             "-an", "-vf", vf, "-c:v", "libx264", "-crf", "14", p],
            cwd=STAB_DIR, check=True)
        res = analyse(gray_frames(p))
        if not res:
            print("%-40s %14s %14s" % (tag, "帧太少", "—"))
            continue
        flag = "  ←" if tag.startswith("不稳定化") else ""
        print("%-40s %14.3f %14.3f%s" % (tag, res[0], res[1], flag))
    print("\n判据：只有『施加分辨率 = 检测分辨率』那一档应**同时低于**『不稳定化（对照）』；"
          "\n      若某档更高，说明它不是在减震而是在**加震**（过校正）。"
          "\n      但**先确认这些数不是噪声底**：旁边那条『不稳定化』本来就不该有残余抖动。"
          "\n      估计器自检：python scripts/res_check.py --selftest（静止必须量出 0）。\n"
          "⚠️ 近乎静止的镜头才测得准；行走/摇镜只能看相对排序。")


if __name__ == "__main__":
    main()
