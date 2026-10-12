# -*- coding: utf-8 -*-
"""多模态素材检索：自然语言 / 一张照片 / 某条素材找相似。

依赖 ``embed_index.py`` 建好的两张新表（只读它们，不写库）：

* ``asset_embed`` —— 每条素材的聚合向量（各帧均值 + L2 归一化）；照片为其自身。
* ``embeddings``   —— 原始向量（``kind`` ∈ frame / text / photo）。

三种用法::

    python embed_search.py --text "有雾的山谷"
    python embed_search.py --photo ../photos/trip/photos/trip/<照片文件>.jpg
    python embed_search.py --similar 0XXX

向量已 L2 归一化，所以**点积即余弦**。

``--text`` 默认对 ``asset_embed``（图像聚合向量）做**跨模态**检索——这是"用自然语言描述画面"
的正路；``--source text`` 则改用 ``embeddings`` 里该素材的**文本向量**（同模态检索，
摘要文字与标签写得好时更准，但看不到摘要没写到的画面）。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlib as M  # noqa: E402

# 换项目要改：EMBED_BASE、mlib.py 里的库路径。
BASE = os.environ.get("EMBED_BASE", "http://127.0.0.1:8087")
MODEL = os.environ.get("EMBED_MODEL", "embeddinggemma2")
FRAME_W = 384
JPEG_Q = 85
QUERY_PREFIX = "task: search result | query: "


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------
def embed_text(text):
    payload = {"model": MODEL, "input": [QUERY_PREFIX + text], "encoding_format": "float"}
    req = urllib.request.Request(BASE + "/v1/embeddings", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    return np.asarray(d["data"][0]["embedding"], dtype=np.float64)


def embed_image(path):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > FRAME_W:
        im = im.resize((FRAME_W, max(1, round(im.height * FRAME_W / im.width))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_Q)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    payload = {"model": MODEL, "input": [{"content": [
        {"type": "image_url", "image_url": {"url": url}}]}]}
    req = urllib.request.Request(BASE + "/v1/embeddings", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    return np.asarray(d["data"][0]["embedding"], dtype=np.float64)


# --------------------------------------------------------------------------
class Index:
    """把 asset_embed（或 embeddings 的文本向量）载进内存矩阵。"""

    def __init__(self, con, source="frames"):
        self.con = con
        self.source = source
        self.nos, vecs, self.n_frames = [], [], []
        if source == "text":
            rows = con.execute(
                "SELECT asset_no, vec FROM embeddings WHERE kind='text' ORDER BY asset_no").fetchall()
            for r in rows:
                self.nos.append(r["asset_no"])
                vecs.append(np.frombuffer(r["vec"], dtype="<f4").astype(np.float64))
                self.n_frames.append(0)
        else:
            rows = con.execute(
                "SELECT asset_no, vec, n_frames FROM asset_embed ORDER BY asset_no").fetchall()
            for r in rows:
                self.nos.append(r["asset_no"])
                vecs.append(np.frombuffer(r["vec"], dtype="<f4").astype(np.float64))
                self.n_frames.append(r["n_frames"])
        self.M = np.vstack(vecs) if vecs else np.zeros((0, 768))
        # 照片 = 不在 assets 表里的 asset_no（照片用文件名主干做主键）
        vids = {r["asset_no"] for r in con.execute("SELECT asset_no FROM assets WHERE kind='video'")}
        self.is_video = np.array([n in vids for n in self.nos])
        self.by_no = {n: i for i, n in enumerate(self.nos)}
        self.meta = {}
        for r in con.execute(
                "SELECT a.asset_no, a.duration_s, a.shot_at_local, a.day, an.summary, an.scene, "
                "an.subject FROM assets a LEFT JOIN analyses an ON an.asset_id=a.id"):
            self.meta[r["asset_no"]] = ("video", r["duration_s"], r["shot_at_local"],
                                        r["summary"], r["scene"], r["subject"])
        for n in self.nos:
            if n not in self.meta:
                day = n.split("-")[0]
                nice = day[:4] + "-" + day[4:6] + "-" + day[6:8] if len(day) == 8 else ""
                self.meta[n] = ("photo", None, nice, None, None, None)

    def load_frames(self):
        """把 ``embeddings(kind='frame')`` 载进来，供 --pool max 用（附带帧时刻）。"""
        nos, vecs, ts = [], [], []
        for r in self.con.execute(
                "SELECT asset_no, t_sec, vec FROM embeddings WHERE kind='frame' ORDER BY asset_no, t_sec"):
            nos.append(r["asset_no"])
            ts.append(r["t_sec"])
            vecs.append(np.frombuffer(r["vec"], dtype="<f4").astype(np.float64))
        self.F = np.vstack(vecs) if vecs else np.zeros((0, 768))
        self.F_no = nos
        self.F_t = ts

    def _collect(self, scores, top, kind, exclude, with_t=None):
        """按 scores 降序取 top，套上 kind/exclude 过滤，补 meta。"""
        idx = np.arange(len(self.nos))
        if kind == "video":
            idx = idx[self.is_video]
        elif kind == "photo":
            idx = idx[~self.is_video]
        if exclude:
            idx = np.array([i for i in idx if self.nos[i] not in exclude], dtype=int)
        if idx.size == 0:
            return []
        idx = idx[np.isfinite(scores[idx])]
        if idx.size == 0:
            return []
        out = []
        for rank, i in enumerate(idx[np.argsort(-scores[idx])][:top], 1):
            k, dur, when, summ, scene, subj = self.meta.get(
                self.nos[i], ("video", None, None, None, None, None))
            hit = {"rank": rank, "asset_no": self.nos[i], "sim": float(scores[i]), "kind": k,
                   "duration_s": dur, "shot_at_local": when, "summary": summ,
                   "scene": scene, "subject": subj,
                   "n_frames": int(self.n_frames[i]) if i < len(self.n_frames) else 0}
            if with_t is not None:
                hit["best_t_sec"] = with_t[i]
            out.append(hit)
        return out

    def rank_max(self, qvec, top=10, kind="all", exclude=()):
        """逐帧取最大相似度（不是均值），并报出命中的那一帧时刻。"""
        if not hasattr(self, "F"):
            self.load_frames()
        fs = self.F @ qvec
        best = np.full(len(self.nos), -np.inf)
        best_t = np.full(len(self.nos), np.nan)
        for n, t, s in zip(self.F_no, self.F_t, fs):
            i = self.by_no.get(n)
            if i is not None and s > best[i]:
                best[i], best_t[i] = s, t
        return self._collect(best, top, kind, exclude, with_t=best_t)

    def rank(self, qvec, top=10, kind="all", exclude=()):
        return self._collect(self.M @ qvec, top, kind, exclude)

    def rank_fuse(self, tx, qvec, top=10, kind="all", exclude=()):
        """图像聚合分与文本分各自 min-max 归一化后等权相加（只有视频两路齐全）。"""
        sf = self.M @ qvec
        st = tx.M @ qvec

        def mm(s):
            lo, hi = float(np.min(s)), float(np.max(s))
            return (s - lo) / (hi - lo) if hi > lo else np.zeros_like(s)

        nf, nt = mm(sf), mm(st)
        scores = np.full(len(self.nos), -np.inf)
        for i, n in enumerate(self.nos):
            j = tx.by_no.get(n)
            if j is not None:
                scores[i] = 0.5 * nf[i] + 0.5 * nt[j]
        return self._collect(scores, top, kind, exclude)


def first40(s):
    if not s:
        return "(无摘要)"
    s = " ".join(str(s).split())
    return s[:40] + ("…" if len(s) > 40 else "")


def show(title, hits, as_json=False, with_t=False):
    log("\n" + title)
    if not hits:
        log("   (无结果)")
        return
    log("   %-3s %-20s %-8s %-7s %-22s %s"
        % ("#", "素材号", "相似度", "命中帧" if with_t else "类型", "拍摄时间", "摘要(前40字)"))
    for h in hits:
        dur = "--" if h["duration_s"] is None else "%.1fs" % h["duration_s"]
        when = h["shot_at_local"] or "--"
        mid = ("%.1fs" % h["best_t_sec"]) if with_t else ("照片" if h["kind"] == "photo" else dur)
        log("   %-3d %-20s %-8.4f %-7s %-22s %s"
            % (h["rank"], h["asset_no"], h["sim"], mid, when, first40(h["summary"])))
    if as_json:
        log(json.dumps(hits, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="素材库多模态检索")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", help="自然语言查询")
    g.add_argument("--photo", help="用一张照片检索")
    g.add_argument("--similar", help="找与该素材号最像的其他素材")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--kind", choices=["all", "video", "photo"], default=None,
                    help="候选范围；--photo 默认 video，其余默认 all")
    ap.add_argument("--source", choices=["frames", "text", "fuse"], default="frames",
                    help="--text 用哪套向量：frames=图像聚合（跨模态，默认）/ text=摘要文本向量"
                         " / fuse=两路分归一化后等权相加（只有视频两路齐全；本项目实测 3 个查询里 "
                         "top-1 命中 2 个，另两路各命中 0 和 1 个）")
    ap.add_argument("--pool", choices=["mean", "max"], default="mean",
                    help="mean=asset_embed 各帧均值（默认）/ max=直接在 embeddings 的逐帧向量上取最大，"
                         "并报出命中的那一帧时刻（长镜头里只有几秒有目标时更稳）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(M.DB + ".bak"):
        log("[warn] 没看到 medialib.db.bak")
    con = M.connect(readonly=True)
    for t in ("asset_embed", "embeddings"):
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
            raise SystemExit("缺少表 %s，请先跑 embed_index.py" % t)

    source = args.source
    kind = args.kind
    if source in ("text", "fuse") and args.text is None:
        raise SystemExit("--source %s 只对 --text 有意义" % source)
    if source == "fuse" and args.pool == "max":
        raise SystemExit("--source fuse 与 --pool max 不能同时用（两条路径打分口径不同）")
    if source == "text" and args.pool == "max":
        raise SystemExit("--source text 与 --pool max 不能同时用（max 走的是逐帧图像向量）")
    if source == "fuse" and args.kind == "photo":
        raise SystemExit("--source fuse 需要文本向量，照片没有，请用 --source frames")

    ix = Index(con, source="text" if source == "text" else "frames")
    label = {"frames": "asset_embed(图像聚合)", "text": "embeddings(kind=text)",
             "fuse": "图像聚合 + 文本 两路归一化等权相加（仅视频）"}[source]
    if source == "fuse":
        tx = Index(con, source="text")
    log("索引：%d 条素材（视频 %d / 照片 %d），来源=%s，池化=%s"
        % (len(ix.nos), int(ix.is_video.sum()), int((~ix.is_video).sum()), label, args.pool))

    def go(qvec, title, exclude=()):
        if source == "fuse":
            show(title + "  [fuse]",
                 ix.rank_fuse(tx, qvec, args.top, "video" if kind == "all" else kind, exclude),
                 args.json)
        elif args.pool == "max":
            show(title + "  [逐帧 max]",
                 ix.rank_max(qvec, args.top, kind, exclude), args.json, with_t=True)
        else:
            show(title, ix.rank(qvec, args.top, kind, exclude), args.json)

    if args.text:
        kind = kind or "all"
        go(embed_text(args.text), "查询：%s        [%s / kind=%s]" % (args.text, source, kind))
    elif args.photo:
        kind = kind or "video"           # "用一张照片找出它对应的视频"
        stem = os.path.splitext(os.path.basename(args.photo))[0]
        go(embed_image(args.photo),
           "照片：%s        [kind=%s]" % (args.photo, kind), exclude={stem})
    else:
        kind = kind or "all"
        no = str(args.similar).lstrip("#").strip()
        if no not in ix.by_no:
            raise SystemExit("asset_embed 里没有 %s" % no)
        go(ix.M[ix.by_no[no]],
           "与 %s 最相似的素材        [%s / kind=%s]" % (no, source, kind), exclude={no})
    con.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                 # noqa: BLE001
        pass
    main()
