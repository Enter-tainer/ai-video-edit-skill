# -*- coding: utf-8 -*-
"""每天的素材盘点，给"分日重挑"的 subagent 用。

用法:
  python day_inventory.py                 # 所有天
  python day_inventory.py <YYYY-MM-DD>    # 指定一天，打印该天全部素材
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlib as M  # noqa: E402


def main():
    con = M.connect(readonly=True)
    day = sys.argv[1] if len(sys.argv) > 1 else None
    if not day:
        q = """SELECT a.day, COUNT(*) n, SUM(a.duration_s)/60.0 mins,
               SUM(CASE WHEN n.keep_score>=4 THEN 1 ELSE 0 END) k4
               FROM assets a LEFT JOIN analyses n ON n.asset_id=a.id
               WHERE a.kind='video' GROUP BY a.day ORDER BY a.day"""
        for r in con.execute(q):
            print("%s  n=%3d  %5.1f min  keep>=4:%3d" % (r["day"], r["n"], r["mins"], r["k4"]))
        return
    q = """SELECT a.asset_no, a.shot_at_local, a.duration_s, a.has_audio,
                  n.keep_score, n.role, n.scene, n.subject, n.camera_move,
                  n.quality, n.issues, n.summary
           FROM assets a LEFT JOIN analyses n ON n.asset_id=a.id
           WHERE a.kind='video' AND a.day=? ORDER BY a.shot_at_local"""
    for r in con.execute(q, (day,)):
        t = (r["shot_at_local"] or "")[11:19]
        print("%s %s %6.1fs keep=%s %-12s %-10s %-8s %s" % (
            r["asset_no"], t, r["duration_s"] or 0, r["keep_score"], r["role"] or "-",
            r["scene"] or "-", r["camera_move"] or "-", r["quality"] or "-"))
        print("      issues=%s" % (r["issues"] or "无"))
        print("      %s" % (r["summary"] or ""))


if __name__ == "__main__":
    main()
