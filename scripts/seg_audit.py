# -*- coding: utf-8 -*-
"""逐段核对：分镜表里每一行的"应有秒数" vs 分段文件"实际秒数"。

用来抓"分段都对、拼起来却短了"的问题（concat -c copy 会因为时间基/帧数不一致丢时间）。
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlib as M  # noqa: E402
import render_plan as R  # noqa: E402


def dur(p):
    r = subprocess.run([M.FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def main():
    sl = sys.argv[1] if len(sys.argv) > 1 else "shotlist_b.json"
    rows = json.load(open(os.path.join(M.ROOT, sl), encoding="utf-8-sig"))["rows"]
    want = have = 0.0
    bad = []
    for i, r in enumerate(rows, 1):
        d = (float(r["dur"]) if (r.get("photo") or r.get("card"))
             else float(r["tout"]) - float(r["tin"]))
        seg = os.path.join(R.WORK, R.seg_key(r).replace(".", "_") + ".mp4")
        a = dur(seg) if os.path.exists(seg) else None
        want += d
        have += (a or 0.0)
        flag = ""
        if a is None:
            flag = "  ** 缺分段 **"
        elif abs(a - d) > 0.25:
            flag = "  ** 差 %.1fs **" % (a - d)
            bad.append((i, r.get("no") or r.get("photo"), d, a))
        print("%02d %-28s 应有 %5.1fs  实际 %s%s"
              % (i, (r.get("no") or r.get("photo") or "CARD")[:28], d,
                 ("%5.1fs" % a) if a is not None else "   -  ", flag))
    print("\n应有合计 %.1fs   分段实际合计 %.1fs   差 %+.1fs" % (want, have, have - want))
    if bad:
        print("对不上的 %d 段：" % len(bad))
        for i, n, d, a in bad:
            print("   #%02d %s 应有 %.1f 实际 %.1f" % (i, n, d, a))


if __name__ == "__main__":
    main()
