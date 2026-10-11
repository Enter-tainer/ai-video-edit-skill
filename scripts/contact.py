# -*- coding: utf-8 -*-
"""把若干条素材抽帧拼成一张联系表（contact sheet），用来人眼比选镜头。

用法: python contact.py --out x.png --frames 5 <素材号> <素材号> ...
每行一条素材，从左到右是这条素材按时间均匀取的 N 帧，左上角标素材号 + 拍摄时间。
"""
import argparse
import os
import subprocess
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mlib as M  # noqa: E402

CELL_W, CELL_H = 384, 216
LABEL_H = 22
PAD = 4


def frames_of(src, dur, n, tin=0.0, tout=None):
    tout = dur if tout is None else tout
    span = max(0.1, tout - tin)
    out = []
    for i in range(n):
        t = tin + span * (i + 0.5) / n
        out.append(t)
    return out


def extract(src, ts, cache):
    imgs = []
    for t in ts:
        p = os.path.join(cache, f"{os.path.basename(src)}_{t:.2f}.png")
        if not os.path.exists(p):
            subprocess.run([M.FFMPEG, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", src,
                            "-frames:v", "1", "-vf",
                            f"scale={CELL_W}:{CELL_H}:force_original_aspect_ratio=decrease,"
                            f"pad={CELL_W}:{CELL_H}:(ow-iw)/2:(oh-ih)/2:color=black",
                            p], check=True)
        imgs.append(Image.open(p).convert("RGB"))
    return imgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nos", nargs="+")
    ap.add_argument("--frames", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default=os.path.join(M.ROOT, "work", "contact"))
    ap.add_argument("--tin", type=float, default=0.0)
    ap.add_argument("--tout", type=float, default=None)
    a = ap.parse_args()

    os.makedirs(a.cache, exist_ok=True)
    con = M.connect(readonly=True)
    W = a.frames * CELL_W + (a.frames + 1) * PAD
    H = len(a.nos) * (CELL_H + LABEL_H) + (len(a.nos) + 1) * PAD
    sheet = Image.new("RGB", (W, H), (26, 26, 30))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageDraw.Draw(sheet).getfont("consolab.ttf", 15)
    except Exception:
        font = None

    for row, no in enumerate(a.nos):
        r = con.execute("SELECT path, duration_s, shot_at_local FROM assets "
                        "WHERE asset_no=?", (no,)).fetchone()
        y = PAD + row * (CELL_H + LABEL_H + PAD)
        if not r:
            d.text((PAD + 4, y + 4), f"{no}  (not in library)", fill=(255, 90, 90), font=font)
            continue
        dur = float(r["duration_s"] or 0)
        tin = a.tin
        tout = min(dur, a.tout) if a.tout else dur
        ts = frames_of(r["path"], dur, a.frames, tin, tout)
        imgs = extract(r["path"], ts, a.cache)
        for c, im in enumerate(imgs):
            x = PAD + c * (CELL_W + PAD)
            sheet.paste(im, (x, y + LABEL_H))
            d.text((x + 3, y + CELL_H + LABEL_H - 14), f"{ts[c]:.1f}s",
                   fill=(210, 210, 210), font=font)
        tm = (r["shot_at_local"] or "")[11:19]
        d.text((PAD + 4, y + 3), f"{no}   {tm}   {dur:.1f}s",
               fill=(255, 235, 120), font=font)
    sheet.save(a.out)
    print(f"wrote {a.out}  {W}x{H}")


if __name__ == "__main__":
    main()
