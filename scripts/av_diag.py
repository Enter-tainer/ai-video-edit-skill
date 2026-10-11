"""给每个用到的镜头量两件事：抖不抖、原声是水声还是风噪。

· 抖动：用 vidstabdetect 的 trf（逐帧全局运动），取相邻帧平移量的**抖动分量**
  （帧间差分的 RMS）——平稳摇镜的差分小，手持抖动的大。
· 原声：算 500–8000Hz 能量 / 0–200Hz 能量。水流是宽带的（比值高），
  风噪集中在低频（比值极低）。据此决定这个镜头要不要静音。

用法: python av_diag.py shotlist_v3_c.json [--out av_diag.json]
"""
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlib as M

SR = 22050


def shake_score(src, tin, tout, tmpdir):
    r"""vidstabdetect → trf → 帧间平移抖动 RMS（像素，按 480 宽归一）。

    注意：trf 路径不能直接写 Windows 绝对路径——滤镜串里 `:` 是参数分隔符，
    形如 `<盘符>:\<目录>\t.trf` 的写法会把 result 拆断。所以 cwd 切到临时目录、用相对文件名。
    """
    r = subprocess.run([M.FFMPEG, "-v", "error", "-y", "-ss", f"{tin:.2f}",
                        "-t", f"{tout - tin:.2f}", "-i", src,
                        "-vf", "scale=480:-2,vidstabdetect=shakiness=10:accuracy=15:"
                               "result=t.trf:fileformat=ascii",
                        "-f", "null", "-"], capture_output=True, text=True,
                       errors="replace", cwd=tmpdir)
    trf = os.path.join(tmpdir, "t.trf")
    if not os.path.exists(trf):
        return None
    dx, dy = [], []
    for ln in open(trf, encoding="utf-8", errors="replace"):
        p = ln.split()
        if len(p) >= 6:
            try:
                dx.append(float(p[4]))
                dy.append(float(p[5]))
            except ValueError:
                pass
    if len(dx) < 6:
        return None
    jx = np.diff(np.array(dx))
    jy = np.diff(np.array(dy))
    return float(np.sqrt((jx ** 2 + jy ** 2).mean()))


def amb_class(src, tin, tout):
    """(500-8k)/(0-200) 能量比 + 低频占比。"""
    r = subprocess.run([M.FFMPEG, "-v", "error", "-ss", f"{tin:.2f}",
                        "-t", f"{tout - tin:.2f}", "-i", src, "-vn", "-ac", "1",
                        "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, dtype="<f4").astype(np.float64)
    if len(x) < SR // 2:
        return None
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    tot = X.sum() + 1e-20
    lo = X[f < 200].sum() / tot
    hi = X[(f >= 500) & (f <= 8000)].sum() / tot
    mid = X[(f >= 200) & (f < 500)].sum() / tot
    return {"ratio": float(hi / (lo + 1e-12)), "low_share": float(lo), "mid_share": float(mid)}


def main():
    sl = sys.argv[1] if len(sys.argv) > 1 else "shotlist_v3_c.json"
    rows = json.load(open(os.path.join(M.ROOT, sl), encoding="utf-8-sig"))["rows"]
    con = M.connect(readonly=True)
    out, seen = {}, {}
    tmpdir = tempfile.mkdtemp()
    for r in rows:
        no = r.get("no")
        if not no or r.get("photo") or r.get("file"):
            continue
        if no in seen:                      # 同一个素材用两次只量一次（取更长的那段）
            if (r["tout"] - r["tin"]) <= seen[no]:
                continue
        seen[no] = r["tout"] - r["tin"]
        p = con.execute("SELECT path FROM assets WHERE asset_no=?", (no,)).fetchone()["path"]
        s = shake_score(p, float(r["tin"]), float(r["tout"]), tmpdir)
        a = amb_class(p, float(r["tin"]), float(r["tout"]))
        out[no] = {"shake": None if s is None else round(s, 3),
                   "amb": None if a is None else {k: round(v, 4) for k, v in a.items()},
                   "desc": (r.get("desc") or "")[:34]}
    order = sorted(out, key=lambda k: -(out[k]["shake"] or 0))
    print(f"{'素材':8} {'抖动':>7}  {'水/风比':>8} {'低频占比':>8}  说明")
    for no in order:
        v = out[no]
        a = v["amb"] or {}
        print(f"{no:8} {v['shake'] if v['shake'] is not None else -1:7.3f}  "
              f"{a.get('ratio', 0):8.3f} {a.get('low_share', 0) * 100:7.1f}%  {v['desc']}")
    dst = sys.argv[3] if len(sys.argv) > 3 else os.path.join(M.ROOT, "av_diag.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("->", dst)


if __name__ == "__main__":
    main()
