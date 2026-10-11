# -*- coding: utf-8 -*-
"""按"抖动"给候选镜头排序（相位相关法，比 vidstab 的 trf 单位可靠）。

做法：把窗口解成 480x270 灰度、按成片帧率 30fps，逐帧用**相位相关**估全局平移，
再取高频残差：
    hf = d - moving_average(d, 15帧≈0.5s)
    shake_px = std(hf) * 1920        # 折算到 1080p 画幅上"每帧抖多少像素"
    pan_px_s = |mean(d)| * 1920 * 30 # 有意为之的运镜速度
只有"高频抖动"才是手持不稳；平稳的摇镜不该被判成抖。

用法: python shake_rank2.py <素材号> <素材号> ...
      python shake_rank2.py --win <素材号>:<入点>:<出点> ...
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlib as M  # noqa: E402

W, H = 480, 270
REF = 1920
WIN = 15


def gray_frames(path, tin, tout):
    r = subprocess.run([M.FFMPEG, "-v", "error", "-ss", f"{tin}", "-t", f"{tout - tin}",
                        "-i", path, "-vf", f"scale={W}:{H},fps=30", "-pix_fmt", "gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    return a[: (len(a) // (W * H)) * W * H].reshape(-1, H, W).astype(np.float32)


def phase_shift(f1, f2):
    """相位相关估 f1->f2 的全局平移 (dy, dx)。"""
    F1 = np.fft.rfft2(f1 - f1.mean())
    F2 = np.fft.rfft2(f2 - f2.mean())
    R = F1 * np.conj(F2)
    R /= np.abs(R) + 1e-9
    c = np.fft.irfft2(R, s=(H, W))
    iy, ix = np.unravel_index(np.argmax(c), c.shape)
    dy = iy if iy <= H // 2 else iy - H
    dx = ix if ix <= W // 2 else ix - W
    return float(dy), float(dx)


def analyse(a):
    if len(a) < 10:
        return None
    d = np.array([phase_shift(a[i], a[i + 1]) for i in range(len(a) - 1)])
    w = min(WIN, max(3, len(d) // 3))
    k = np.ones(w) / w
    hf = np.stack([d[:, 0] - np.convolve(d[:, 0], k, "same"),
                   d[:, 1] - np.convolve(d[:, 1], k, "same")], axis=1)
    shake = float(np.sqrt(np.mean(hf ** 2)) * REF)
    pan = float(np.hypot(d[:, 0].mean(), d[:, 1].mean()) * REF * 30)
    return shake, pan, len(d)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wins = {}
    if "--win" in sys.argv:
        for spec in sys.argv[sys.argv.index("--win") + 1:]:
            if spec.count(":") != 2:
                continue
            no, t0, t1 = spec.split(":")
            wins[no] = (float(t0), float(t1))
    con = M.connect(readonly=True)
    rows = []
    for no in args:
        r = con.execute("SELECT path, duration_s, shot_at_local FROM assets WHERE asset_no=?",
                        (no,)).fetchone()
        if not r:
            print(no, "找不到"); continue
        tin, tout = wins.get(no, (0.0, min(8.0, float(r["duration_s"]))))
        a = gray_frames(r["path"], tin, tout)
        res = analyse(a)
        if not res:
            print(no, "帧太少"); continue
        shake, pan, n = res
        rows.append((shake, no, tin, tout, pan, n, (r["shot_at_local"] or "")[11:19],
                     r["duration_s"]))
    rows.sort(reverse=True)
    print("%-7s %-9s %-14s %10s %10s" % ("素材", "拍摄时间", "窗口", "抖动px/帧", "运镜px/s"))
    for shake, no, tin, tout, pan, n, t, dur in rows:
        print("%-7s %-9s %5.1f-%-7.1f %10.2f %10.0f   (时长%ss)" % (no, t, tin, tout, shake, pan, dur))


if __name__ == "__main__":
    main()
