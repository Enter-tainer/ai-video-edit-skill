# -*- coding: utf-8 -*-
"""量"碎不碎"：各版本的镜头时长分布（只算实拍镜头，不含照片卡与滚屏卡）。

朋友的反馈是"感觉有点碎""我没看够就切下一个镜头了""切碎了就不太沉浸"，
所以这个脚本就是那条反馈的验收口径：
  · 开场要**短**（保留存率的快切）
  · 正文要**长**（沉浸式长镜）
  · 看中位数而不是平均数——平均数会被开场那几刀和个别超长镜带偏

用法: python shot_stats.py
"""
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlib as M  # noqa: E402

VARIANTS = [
    ("shotlist_v5_c.json", "2:30 长镜沉浸版（主推）"),
    ("shotlist_v4_c.json", "3 分钟版"),
    ("shotlist_v3_c.json", "5 分钟版"),
]
# 用带相机插入镜的 `_c` 分镜表：那才是真正渲染的东西（3 条相机镜各 2.8–3.6s，
# 会拉低一点中位数，所以不能用不带 cam 的表来算）。


def dur_of(r):
    if r.get("photo") or r.get("card"):
        return None                      # 静帧/滚屏卡不算"镜头时长"
    return float(r["tout"]) - float(r["tin"])


def main():
    print(f"{'版本':<26}{'总长':>8}{'实拍镜':>7}{'中位':>7}{'平均':>7}{'最短':>7}{'最长':>7}{'≥8s':>6}")
    for name, label in VARIANTS:
        p = os.path.join(M.ROOT, name)
        if not os.path.exists(p):
            continue
        rows = json.load(open(p, encoding="utf-8-sig"))["rows"]
        total = sum((r["dur"] if (r.get("photo") or r.get("card")) else dur_of(r))
                    for r in rows)
        ds = [d for d in (dur_of(r) for r in rows) if d]
        long_n = sum(1 for d in ds if d >= 8.0)
        print(f"{label:<26}{total:7.1f}s{len(ds):7d}{st.median(ds):6.1f}s"
              f"{st.mean(ds):6.1f}s{min(ds):6.1f}s{max(ds):6.1f}s{long_n:6d}")

    print("\n—— 开场（应该很短，保留存率）——")
    for name, label in VARIANTS:
        p = os.path.join(M.ROOT, name)
        if not os.path.exists(p):
            continue
        rows = json.load(open(p, encoding="utf-8-sig"))["rows"]
        op = [dur_of(r) for r in rows if r.get("seg", "").startswith("开场") and dur_of(r)]
        print(f"{label:<26} {len(op)} 刀: " + " ".join(f"{d:.1f}" for d in op)
              + f"   合计 {sum(op):.1f}s  中位 {st.median(op):.1f}s")

    print("\n—— 正文（应该很长，沉浸感）——")
    for name, label in VARIANTS:
        p = os.path.join(M.ROOT, name)
        if not os.path.exists(p):
            continue
        rows = json.load(open(p, encoding="utf-8-sig"))["rows"]
        body = [dur_of(r) for r in rows
                if r.get("seg", "").startswith("第") and dur_of(r)]
        long_n = sum(1 for d in body if d >= 8.0)
        print(f"{label:<26} {len(body)} 镜: 中位 {st.median(body):4.1f}s  "
              f"平均 {st.mean(body):4.1f}s  最长 {max(body):4.1f}s  ≥8s 有 {long_n} 镜")

    print("\n—— 2:30 主推版的逐镜时长（正文）——")
    rows = json.load(open(os.path.join(M.ROOT, "shotlist_v5_c.json"),
                          encoding="utf-8-sig"))["rows"]
    for r in rows:
        d = dur_of(r)
        if not d:
            continue
        lbl = (r.get("no") or r.get("photo", "")[:20])
        print(f"   {r['seg']:<14} {lbl:<12} {d:5.1f}s  {(r.get('type') or '')[:16]}")


if __name__ == "__main__":
    main()
