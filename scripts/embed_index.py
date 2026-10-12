# -*- coding: utf-8 -*-
"""为已有素材库建立**多模态 embedding 索引**（视频帧 + 文本 + 照片）。

服务：局域网上的 EmbeddingGemma 2（OpenAI 兼容 /v1/embeddings），768 维、已 L2 归一化。
  - 文本必须带任务前缀：文档侧 ``title: {标题} | text: {正文}``；
    检索侧 ``task: search result | query: {q}``。
  - 图片走 OpenAI 的 content 数组，**不加前缀**；缩到宽 384 的 JPEG 再 base64。

产出的新表（只新增，不动任何已有表）::

    embeddings(asset_no TEXT, kind TEXT, t_sec REAL, dim INT, vec BLOB)
    asset_embed(asset_no TEXT PRIMARY KEY, dim INT, vec BLOB, n_frames INT)

``kind`` ∈ {'frame', 'text', 'photo'}；``vec`` 为 float32 小端字节（dim=768）。
``asset_embed.vec`` = 该素材各帧向量的均值，再做 L2 归一化（照片则为其自身，n_frames=1）。

用法::

    python embed_index.py                 # 全量（视频 3 帧 + 文本，照片 1 图），断点续跑
    python embed_index.py --only-video    # 只做视频
    python embed_index.py --only-photo    # 只做照片
    python embed_index.py --force         # 忽略已有结果，重算
    python embed_index.py --limit 5       # 只做前 5 条素材（冒烟测试）

断点续跑：``asset_embed`` 里已有该 asset_no 就跳过（--force 时重算）。
每条素材一个事务、写完即 commit；重算时会先删掉该素材的旧行，保证可重复执行。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlib as M  # noqa: E402

# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
# 换项目要改：EMBED_BASE（embedding 服务地址）、mlib.py 里的库路径、照片目录。
BASE = os.environ.get("EMBED_BASE", "http://127.0.0.1:8087")
MODEL = os.environ.get("EMBED_MODEL", "embeddinggemma2")
DIM = 768

TIMEOUT_COLD = 120.0      # 首个请求：服务冷启动 ~4s，给足余量
TIMEOUT_WARM = 60.0
RETRIES = 3               # 偶发连接被拒时重试

FRAME_W = 384             # 抽帧 / 照片统一缩到宽 384
JPEG_Q = 85

FRAME_FRACS = (0.275, 0.5, 0.725)   # 时长上均匀 3 帧，跳过首尾各 5%
N_FRAMES = len(FRAME_FRACS)

WORK = os.path.join(M.ROOT, "work", "embed")
FRAME_DIR = os.path.join(WORK, "frames")
BAK = M.DB + ".bak"

QUERY_PREFIX = "task: search result | query: "


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
_state = {"first": True, "calls": 0, "retries": 0, "cold_s": None, "warm": []}


def _post(payload, timeout=None):
    if timeout is None:
        timeout = TIMEOUT_COLD if _state["first"] else TIMEOUT_WARM
    req = urllib.request.Request(BASE + "/v1/embeddings",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post_embeddings(payload):
    """带重试的 /v1/embeddings 调用；返回按 index 排序后的 embedding 列表。"""
    last = None
    for attempt in range(RETRIES):
        t0 = time.time()
        try:
            d = _post(payload)
            dt = time.time() - t0
            _state["calls"] += 1
            if _state["first"]:
                _state["first"] = False
                _state["cold_s"] = dt
                log("   [warm] 首个请求 %.2fs（含冷启动）" % dt)
            else:
                _state["warm"].append(dt)
            data = sorted(d["data"], key=lambda x: x.get("index", 0))
            return [x["embedding"] for x in data]
        except Exception as e:                       # noqa: BLE001
            last = e
            if attempt + 1 >= RETRIES:
                break
            _state["retries"] += 1
            wait = 1.5 * (attempt + 1)
            log("   [retry %d/%d] %s: %s —— %.1fs 后重试"
                % (attempt + 1, RETRIES - 1, type(e).__name__, e, wait))
            time.sleep(wait)
    raise RuntimeError("embeddings 调用失败（重试 %d 次）：%r" % (RETRIES, last))


def health():
    with urllib.request.urlopen(BASE + "/health", timeout=TIMEOUT_COLD) as r:
        return json.loads(r.read().decode())


def warmup():
    log("== 0) 服务自检 ==")
    try:
        log("   /health : %s" % health())
    except Exception as e:                            # noqa: BLE001
        raise SystemExit("服务不可达 %s : %r" % (BASE, e))
    v = post_embeddings({"model": MODEL, "input": [QUERY_PREFIX + "warmup"],
                         "encoding_format": "float"})[0]
    log("   /v1/embeddings : dim=%d  |v|=%.6f" % (len(v), float(np.linalg.norm(v))))


def embed_texts(texts):
    return post_embeddings({"model": MODEL, "input": list(texts), "encoding_format": "float"})


def embed_images(urls):
    """批量图片 embedding；批量失败时逐张降级重试。"""
    if not urls:
        return []
    payload = {"model": MODEL, "input": [
        {"content": [{"type": "image_url", "image_url": {"url": u}}]} for u in urls]}
    try:
        out = post_embeddings(payload)
        if len(out) == len(urls):
            return out
        log("   [warn] 批量返回 %d 条，期望 %d 条，改用逐张" % (len(out), len(urls)))
    except Exception as e:                            # noqa: BLE001
        log("   [warn] 批量图片失败（%s），改用逐张" % type(e).__name__)
    return [post_embeddings({"model": MODEL, "input": [
        {"content": [{"type": "image_url", "image_url": {"url": u}}]}]})[0] for u in urls]


# --------------------------------------------------------------------------
# 图片预处理
# --------------------------------------------------------------------------
def _jpeg_data_url(path, maxw=FRAME_W, q=JPEG_Q):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > maxw:
        im = im.resize((maxw, max(1, round(im.height * maxw / im.width))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    raw = buf.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii"), len(raw)


def grab_frame(src, t, dst):
    """抽单帧到 384 宽 JPEG；失败时退到稍早时刻再试一次。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst                                   # 帧缓存，可复用
    for attempt, tt in enumerate((t, max(0.0, t - 0.15))):
        p = subprocess.run([M.FFMPEG, "-v", "error", "-y", "-ss", "%.3f" % tt, "-i", src,
                            "-frames:v", "1", "-vf", "scale=%d:-2" % FRAME_W,
                            "-q:v", "4", dst],
                           capture_output=True, text=True, errors="replace")
        if p.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0:
            return dst
        if attempt == 0:
            continue
        raise RuntimeError("ffmpeg 抽帧失败 @%.2fs: %s" % (t, (p.stderr or "")[:200]))
    raise RuntimeError("ffmpeg 抽帧失败 @%.2fs" % t)


# --------------------------------------------------------------------------
# 向量编解码
# --------------------------------------------------------------------------
def pack(vec):
    a = np.asarray(vec, dtype=np.float64).ravel()
    if a.shape[0] != DIM:
        raise ValueError("维度不是 %d：%d" % (DIM, a.shape[0]))
    return a.astype("<f4").tobytes()


def unpack(blob):
    return np.frombuffer(blob, dtype="<f4")


def l2norm(a):
    a = np.asarray(a, dtype=np.float64).ravel()
    n = float(np.linalg.norm(a))
    return a / n if n > 0 else a


# --------------------------------------------------------------------------
# 建表 / 备份
# --------------------------------------------------------------------------
DDL = """
CREATE TABLE IF NOT EXISTS embeddings (
    asset_no TEXT,
    kind     TEXT,           -- 'frame' | 'text' | 'photo'
    t_sec    REAL,
    dim      INT,
    vec      BLOB
);
CREATE INDEX IF NOT EXISTS idx_embeddings_asset ON embeddings(asset_no);
CREATE INDEX IF NOT EXISTS idx_embeddings_kind  ON embeddings(kind, asset_no);

CREATE TABLE IF NOT EXISTS asset_embed (
    asset_no TEXT PRIMARY KEY,
    dim      INT,
    vec      BLOB,
    n_frames INT
);
"""


def backup_db():
    if os.path.exists(BAK):
        os.remove(BAK)
    src = sqlite3.connect("file:%s?mode=ro" % M.DB.replace("\\", "/"), uri=True)
    dst = sqlite3.connect(BAK)
    try:
        src.backup(dst)                # 在线备份 API：自带 WAL 合并，得到单文件一致副本
    finally:
        dst.close()
        src.close()
    log("   备份 -> %s (%.1f MB)" % (os.path.basename(BAK), os.path.getsize(BAK) / 1e6))


def ensure_schema(con):
    con.executescript(DDL)
    con.commit()


# --------------------------------------------------------------------------
# 语料
# --------------------------------------------------------------------------
def video_text(con, aid, asset_no):
    """``title: {asset_no} | text: {summary 等拼接}``（文档侧前缀）。"""
    r = con.execute("SELECT * FROM analyses WHERE asset_id=?", (aid,)).fetchone()
    parts = []
    if r:
        for k, label in (("summary", None), ("scene", "场景"), ("subject", "主体"),
                         ("action", "动作"), ("camera_move", "运镜"),
                         ("time_of_day", "时段"), ("weather", "天气"),
                         ("shot_size", "景别"), ("light", "光线"),
                         ("issues", "问题")):
            v = r[k]
            if v and str(v).strip():
                parts.append(str(v).strip() if label is None else "%s：%s" % (label, str(v).strip()))
    tags = [x["name"] for x in con.execute(
        "SELECT t.name FROM asset_tags at JOIN tags t ON t.id=at.tag_id "
        "WHERE at.asset_id=? ORDER BY t.name", (aid,))]
    if tags:
        parts.append("标签：" + "、".join(tags))
    body = "；".join(parts) if parts else "(无分析文本)"
    return "title: %s | text: %s" % (asset_no, body), body


def list_videos(con):
    return con.execute("SELECT id, asset_no, path, duration_s FROM assets "
                       "WHERE kind='video' ORDER BY asset_no").fetchall()


def list_photos():
    d = os.path.join(M.ROOT, "photos", "trip")
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            out.append((os.path.splitext(f)[0], os.path.join(d, f)))
    return out


# --------------------------------------------------------------------------
# 单条素材
# --------------------------------------------------------------------------
def already_done(con, asset_no):
    return con.execute("SELECT 1 FROM asset_embed WHERE asset_no=?", (asset_no,)).fetchone() is not None


def _replace(con, asset_no, rows, agg, n_frames, stats):
    """单个事务：清旧行 + 写新行 + 写聚合。"""
    with con:                                          # 自动 BEGIN / COMMIT
        con.execute("DELETE FROM embeddings WHERE asset_no=?", (asset_no,))
        con.executemany(
            "INSERT INTO embeddings (asset_no, kind, t_sec, dim, vec) VALUES (?,?,?,?,?)",
            [(asset_no, k, t, DIM, v) for k, t, v in rows])
        con.execute("INSERT INTO asset_embed (asset_no, dim, vec, n_frames) VALUES (?,?,?,?) "
                    "ON CONFLICT(asset_no) DO UPDATE SET dim=excluded.dim, "
                    "vec=excluded.vec, n_frames=excluded.n_frames",
                    (asset_no, DIM, pack(agg), int(n_frames)))
    stats["embedded"] += 1


def index_video(con, row, stats, force=False):
    no = row["asset_no"]
    if not force and already_done(con, no):
        stats["skipped"] += 1
        return "skip"
    dur = float(row["duration_s"] or 0.0)
    times = [min(max(dur * f, 0.0), max(dur - 0.05, 0.0)) for f in FRAME_FRACS]

    # --- 3 帧 ---
    paths = []
    for i, t in enumerate(times):
        try:
            paths.append(grab_frame(row["path"], t, os.path.join(FRAME_DIR, no, "%d.jpg" % i)))
        except Exception as e:                        # noqa: BLE001
            log("   [frame-fail] %s @%.2fs: %s" % (no, t, e))
    if not paths:
        stats["failed"].append((no, "全部帧抽取失败"))
        return "fail"
    urls = [_jpeg_data_url(p)[0] for p in paths]
    fvecs = embed_images(urls)
    fvecs = [l2norm(v) for v in fvecs]

    # --- 文本 ---
    text, body = video_text(con, row["id"], no)
    tvec = l2norm(embed_texts([text])[0])

    agg = l2norm(np.mean(np.array(fvecs, dtype=np.float64), axis=0))
    rows = [("frame", float(times[i]), pack(fvecs[i])) for i in range(len(fvecs))]
    rows.append(("text", None, pack(tvec)))
    _replace(con, no, rows, agg, len(fvecs), stats)
    return "ok"


def index_photo(con, asset_no, path, stats, force=False):
    if not force and already_done(con, asset_no):
        stats["skipped"] += 1
        return "skip"
    url = _jpeg_data_url(path)[0]
    v = l2norm(embed_images([url])[0])
    _replace(con, asset_no, [("photo", None, pack(v))], v, 1, stats)
    return "ok"


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略已有结果重算")
    ap.add_argument("--only-video", action="store_true")
    ap.add_argument("--only-photo", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只做前 N 条（冒烟测试）")
    ap.add_argument("--skip-backup", action="store_true")
    args = ap.parse_args()

    os.makedirs(FRAME_DIR, exist_ok=True)
    t_start = time.time()
    warmup()

    log("\n== 1) 备份 ==")
    if args.skip_backup:
        log("   跳过（--skip-backup）")
    else:
        backup_db()

    log("\n== 2) 建表 ==")
    con = M.connect()
    con.execute("PRAGMA journal_mode=WAL")
    ensure_schema(con)
    log("   embeddings / asset_embed 就绪")

    videos = [] if args.only_photo else list_videos(con)
    photos = [] if args.only_video else list_photos()
    if args.limit:
        videos = videos[:args.limit]
        photos = photos[:args.limit]

    stats = {"embedded": 0, "skipped": 0, "failed": [], "t_video": 0.0, "t_photo": 0.0}
    stats["todo"] = len(videos) + len(photos)

    log("\n== 3) 视频 %d 条（每条 3 帧 + 1 文本）==" % len(videos))
    t0 = time.time()
    for i, row in enumerate(videos, 1):
        no = row["asset_no"]
        t1 = time.time()
        try:
            r = index_video(con, row, stats, args.force)
        except Exception as e:                        # noqa: BLE001
            stats["failed"].append((no, "%s: %s" % (type(e).__name__, e)))
            log("   [FAIL] %s   %s" % (no, e))
            r = "fail"
        if r == "ok":
            log("   [%3d/%3d] %-6s dur=%6.1fs  (%.2fs/条)" %
                (i, len(videos), no, float(row["duration_s"] or 0), time.time() - t1))
        elif r == "skip" and i % 25 == 0:
            log("   [%3d/%3d] ... 已存在，跳过" % (i, len(videos)))
        stats["t_video"] += time.time() - t1
    log("   视频段耗时 %.1fs（其中 %.1fs 为已跳过/已存在）" % (time.time() - t0, 0.0))

    log("\n== 4) 照片 %d 张 ==" % len(photos))
    t0 = time.time()
    for i, (no, p) in enumerate(photos, 1):
        try:
            index_photo(con, no, p, stats, args.force)
        except Exception as e:                        # noqa: BLE001
            stats["failed"].append((no, "%s: %s" % (type(e).__name__, e)))
            log("   [FAIL] %s  %s" % (no, e))
    stats["t_photo"] = time.time() - t0
    log("   照片段耗时 %.1fs" % stats["t_photo"])

    # --- 收尾 ---
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.commit()

    log("\n== 5) 统计 ==")
    n_emb = con.execute("SELECT count(*) FROM embeddings").fetchone()[0]
    n_agg = con.execute("SELECT count(*) FROM asset_embed").fetchone()[0]
    kinds = con.execute("SELECT kind, count(*) c FROM embeddings GROUP BY kind ORDER BY kind").fetchall()
    log("   embeddings 总行数 = %d" % n_emb)
    for k in kinds:
        log("      kind=%-6s %d" % (k["kind"], k["c"]))
    log("   asset_embed 行数 = %d" % n_agg)
    warm = np.array(_state["warm"]) if _state["warm"] else np.array([0.0])
    timing = {
        "cold_s": _state["cold_s"], "calls": _state["calls"], "retries": _state["retries"],
        "warm_ms_median": float(np.median(warm) * 1000), "warm_ms_p90": float(np.percentile(warm, 90) * 1000),
        "warm_ms_max": float(warm.max() * 1000),
        "total_s": round(time.time() - t_start, 1),
        "embedded": stats["embedded"], "skipped": stats["skipped"],
        "failed": stats["failed"],
        "embeddings_rows": n_emb, "asset_embed_rows": n_agg,
    }
    log("   累计请求 %d 次，重试 %d 次" % (_state["calls"], _state["retries"]))
    log("   首个请求 %.2fs；稳定后每次请求 中位 %.0fms / p90 %.0fms / 最大 %.0fms"
        % (_state["cold_s"] or 0, timing["warm_ms_median"], timing["warm_ms_p90"], timing["warm_ms_max"]))
    log("   总耗时 %.1fs；本次新写 %d 条，跳过 %d 条，失败 %d 条"
        % (timing["total_s"], stats["embedded"], stats["skipped"], len(stats["failed"])))
    if stats["failed"]:
        log("   失败清单：%s" % stats["failed"])

    os.makedirs(WORK, exist_ok=True)
    out = os.path.join(WORK, "index_run.json" if stats["embedded"] else "index_noop.json")
    if not stats["embedded"]:
        log("   本次什么都没写（全是跳过），不覆盖上次的 index_run.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(timing, f, ensure_ascii=False, indent=2)
    log("   运行报告 -> %s" % out)
    con.close()
    return 0 if not stats["failed"] else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                 # noqa: BLE001
        pass
    sys.exit(main())
