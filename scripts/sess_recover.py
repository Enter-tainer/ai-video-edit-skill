# -*- coding: utf-8 -*-
"""把中断掉的一次性 fan-out 里各子 agent 的观察，从它们的会话记录里捞回来。

背景：一次性 fan-out 被 kill 时聚合结果就丢了，但每个子 agent 的会话记录
还在磁盘上，里面有它们逐帧看图写下的观察。

两个坑：
  · 这类日志是增量追加写的，一个 .zstd 里是**多个 zstd 帧首尾相接**，
    Node 的 zstdDecompressSync 只解第一帧 —— 所以交给 unzstd.js 按魔数切帧。
  · 记录形状是 {type, data}，助手消息在 type=="assistant/message" 的 data.message.content 里，
    文本块分 type=="text" 与 type=="reasoning" 两种，两种都要取。

用法：
  设环境变量 SESS_DIR（会话目录）/ 可选 NODE_BIN（node 可执行文件）；
  产出 work/sess/<id>.txt（整段助手文本）+ 屏幕上的摘要 + work/sess/index.json。

  SESS_DIR=<会话目录> NODE_BIN=<node> python sess_recover.py
"""
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlib as M  # noqa: E402

# 换项目时改这两个（也可以用环境变量覆盖）
SESS = os.environ.get("SESS_DIR", r"<会话记录目录>")
NODE = os.environ.get("NODE_BIN", "node")
UNZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unzstd.js")
OUT = os.path.join(M.ROOT, "work", "sess")
# 可选：跳过主会话自己的记录（只统计子 agent）
MAIN = os.environ.get("MAIN_SESSION_ID", "")


def blocks(msg):
    c = msg.get("content")
    out = []
    if isinstance(c, str):
        return [c]
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") in ("text", "reasoning"):
                out.append(b.get("text") or "")
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for d in sorted(glob.glob(os.path.join(SESS, "*"))):
        sid = os.path.basename(d)
        if sid == MAIN:
            continue
        zf = next(iter(glob.glob(os.path.join(d, "*.zstd"))), None)
        if not zf:
            continue
        jf = os.path.join(OUT, sid + ".jsonl")
        if not os.path.exists(jf):
            r = subprocess.run([NODE, UNZ, zf, jf], capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0:
                continue
        lines = open(jf, encoding="utf-8", errors="replace").read().splitlines()
        hdr = {}
        steps = 0
        texts = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                o = json.loads(ln)
            except Exception:
                continue
            t = o.get("type")
            if t == "session":
                hdr = o
            elif t == "step/start":
                steps += 1
            elif t == "assistant/message":
                for s in blocks(o.get("data", {}).get("message", {})):
                    if s and s.strip():
                        texts.append(s)
        if not texts:
            continue
        body = "\n\n".join(texts)
        tf = os.path.join(OUT, sid + ".txt")
        open(tf, "w", encoding="utf-8").write(body)
        # 有没有产出最终的结构化结论（按你自己的 JSON 字段名改）
        tail = body[-1200:]
        KEYS = json.loads(os.environ.get("FINAL_KEYS", '["clips","ordered_shortlist","verified","final_order"]'))
        has_json = any(('"%s"' % k) in body for k in KEYS)
        rows.append({"id": sid, "steps": steps, "chars": len(body),
                     "json": has_json, "file": os.path.basename(tf),
                     "tail": tail.replace("\n", " ")[-260:]})

    rows.sort(key=lambda r: -r["chars"])
    print("%-38s %5s %8s %5s  %s" % ("session", "步", "字数", "JSON", "末尾"))
    for r in rows:
        print("%-38s %5d %8d %5s  %s" % (r["id"], r["steps"], r["chars"],
                                         "有" if r["json"] else "-", r["tail"][:150]))
    print("\n共 %d 个子 agent 的记录 -> %s" % (len(rows), OUT))
    json.dump(rows, open(os.path.join(OUT, "index.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
