# -*- coding: utf-8 -*-
"""查"糊"到底糊在哪一步。

链路里有三次重采样，逐个隔离：
  源 4K →(1) 裁切 →(2) 缩放 1080 →(3) vidstabtransform 逐帧重采样 →(4) 编码
vidstabtransform 在**输出分辨率**上做，等于在 1080p 上再重采样一次；
如果把它放回 4K 再缩放，误差会被缩放平均掉，通常更锐。
另外 `interpol=bicubic` 比 lanczos 软。

指标：拉普拉斯方差（越大越锐）+ 高频能量占比。都在 1080p 上比。
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlib as M  # noqa: E402

CLIP = sys.argv[1] if len(sys.argv) > 1 else "<素材号>"
TIN = float(sys.argv[2]) if len(sys.argv) > 2 else 14.0


def frames(path, w=1920, h=1080):
    r = subprocess.run([M.FFMPEG, "-v", "error", "-i", path, "-vf", f"scale={w}:{h}",
                        "-pix_fmt", "gray", "-f", "rawvideo", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    return a[: (len(a) // (w * h)) * w * h].reshape(-1, h, w).astype(np.float32)


def sharp(a):
    """拉普拉斯方差（对每帧算再取中位）。"""
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    out = []
    for f in a:
        lap = (f[1:-1, 1:-1] * k[1, 1] + f[:-2, 1:-1] * k[0, 1] + f[2:, 1:-1] * k[2, 1]
               + f[1:-1, :-2] * k[1, 0] + f[1:-1, 2:] * k[1, 2])
        out.append(lap.var())
    return float(np.median(out)) if out else 0.0


def main():
    con = M.connect(readonly=True)
    src = con.execute("SELECT path FROM assets WHERE asset_no=?", (CLIP,)).fetchone()["path"]
    trfdir = os.path.join(M.ROOT, "roughcut", "trf")
    work = os.path.join(M.ROOT, "work")
    os.makedirs(work, exist_ok=True)
    trfname = "sharp_%s.trf" % CLIP
    subprocess.run([M.FFMPEG, "-v", "error", "-y", "-ss", str(TIN), "-t", "3", "-i", src, "-an",
                    "-vf", f"scale=1280:-2,vidstabdetect=shakiness=10:accuracy=15:result={trfname}",
                    "-f", "null", "-"], cwd=trfdir, check=True)

    cases = [
        ("① 源4K→1080（参考，不裁不稳）", "scale=1920:1080:flags=lanczos"),
        ("② 现状：裁1.08→1080→vidstab(interpol=1 bicubic)",
         f"crop=iw/1.08:ih/1.08,scale=1920:1080:flags=lanczos,"
         f"vidstabtransform=input={trfname}:smoothing=30:optzoom=2:interpol=1"),
        ("③ 同上但 interpol=2 (lanczos)",
         f"crop=iw/1.08:ih/1.08,scale=1920:1080:flags=lanczos,"
         f"vidstabtransform=input={trfname}:smoothing=30:optzoom=2:interpol=2"),
        ("④ vidstab 在4K做→再缩1080（interpol=2）",
         f"crop=iw/1.08:ih/1.08,vidstabtransform=input={trfname}:smoothing=30:optzoom=2:interpol=2,"
         f"scale=1920:1080:flags=lanczos"),
        ("⑤ 只裁不缩、不稳定（看裁切本身的损失）",
         "crop=iw/1.08:ih/1.08,scale=1920:1080:flags=lanczos"),
    ]
    print("素材 %s  @%.1fs\n" % (CLIP, TIN))
    print("%-46s %12s %8s" % ("", "拉普拉斯方差", "相对参考"))
    ref = None
    for tag, vf in cases:
        p = os.path.join(work, "sharp_%d.mp4" % abs(hash(tag)))
        r = subprocess.run([M.FFMPEG, "-v", "error", "-y", "-ss", str(TIN), "-t", "2", "-i", src, "-an",
                            "-vf", vf, "-c:v", "libx264", "-crf", "14", p],
                           cwd=trfdir, capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            print("%-46s %12s   %s" % (tag, "失败", (r.stderr or "").strip()[:60]))
            continue
        s = sharp(frames(p))
        if ref is None:
            ref = s
        print("%-46s %12.1f %7.0f%%" % (tag, s, 100.0 * s / ref))


if __name__ == "__main__":
    main()
