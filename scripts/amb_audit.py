# -*- coding: utf-8 -*-
"""按"这段画面里到底有没有值得留的声音"给每个用到的镜头定性。

判据沿用 av_diag.amb_class：(500–8000Hz) 与 (<200Hz) 的能量比。
运动相机的风噪 90% 以上能量在 150Hz 以下，所以：
  · ratio 高  = 中高频里有真东西（水声、树叶、脚步、说话）
  · ratio 低  = 基本只有风噪（压到听不见）
再叠一个绝对电平门槛：整段本来就极安静（mid 很低）的，留着也没意义。

输出一张表 + 建议的 AMB_KEEP 集合。

用法:
  python amb_audit.py                 # 合并三个长度的所有窗口
  python amb_audit.py --sl shotlist_v3_c.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import av_diag as A  # noqa: E402
import mlib as M  # noqa: E402

# 判为"留同期声"的门槛：中高频能量至少要到低频的 12%（≈ −9 dB）
RATIO_KEEP = 0.12

SHOTLISTS = ("shotlist_v5_c.json", "shotlist_v3_c.json", "shotlist_v4_c.json",
             "shotlist_v5.json", "shotlist_v3.json", "shotlist_v4.json")


def windows(shotlists):
    """asset_no -> (tin, tout)：同一个素材用两次只量一次，取最长的那个窗口。"""
    best = {}
    for name in shotlists:
        p = os.path.join(M.ROOT, name)
        if not os.path.exists(p):
            continue
        for r in json.load(open(p, encoding="utf-8-sig"))["rows"]:
            no = r.get("no")
            if not no or r.get("photo") or r.get("card") or r.get("file"):
                continue
            tin, tout = float(r["tin"]), float(r["tout"])
            if no not in best or (tout - tin) > (best[no][1] - best[no][0]):
                best[no] = (tin, tout)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sl", nargs="*", default=list(SHOTLISTS))
    ap.add_argument("--ratio", type=float, default=RATIO_KEEP)
    ap.add_argument("--out", default=os.path.join(M.ROOT, "amb_audit.json"))
    a = ap.parse_args()

    con = M.connect(readonly=True)
    paths = {r["asset_no"]: r["path"]
             for r in con.execute("SELECT asset_no, path FROM assets")}
    wins = windows(a.sl)
    print(f"量 {len(wins)} 条用到的素材（各取最长的使用窗口）…\n", flush=True)

    rows = []
    for no, (tin, tout) in sorted(wins.items()):
        src = paths.get(no)
        if not src or not os.path.exists(src):
            continue
        d = A.amb_class(src, tin, tout)
        if not d:
            continue
        rows.append({"no": no, "tin": round(tin, 2), "tout": round(tout, 2),
                     "ratio": round(d["ratio"], 4),
                     "low_share": round(d["low_share"] * 100, 1),
                     "mid_share": round(d["mid_share"] * 100, 1)})

    rows.sort(key=lambda r: -r["ratio"])
    print(f"{'素材':<7}{'窗口':>14}{'水/风比':>9}{'低频占比':>9}  建议")
    keep = []
    for r in rows:
        k = r["ratio"] >= a.ratio
        if k:
            keep.append(r["no"])
        print(f"{r['no']:<7}{r['tin']:6.1f}-{r['tout']:5.1f}{r['ratio']:9.3f}"
              f"{r['low_share']:8.1f}%  {'留同期声' if k else '静音'}")

    print(f"\n留同期声的 {len(keep)} 条：{', '.join(keep)}")
    print(f"（门槛 ratio ≥ {a.ratio}）")
    json.dump({"ratio_keep": a.ratio, "keep": keep, "rows": rows},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("->", a.out)


if __name__ == "__main__":
    main()
