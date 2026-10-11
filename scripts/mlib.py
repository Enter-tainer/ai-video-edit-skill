"""公共库：路径、ffprobe/ffmpeg 封装、DB 连接。"""
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone

# ⚠️ 换项目时改这里（可用环境变量覆盖，方便多项目复用）
ROOT = os.environ.get("EDIT_ROOT", r"<项目根目录，例如 D:\work\myedit>")
SRC = os.environ.get("EDIT_SRC", r"<原始素材目录>")
DB = os.path.join(ROOT, "tools", "medialib.db")
SCHEMA = os.path.join(ROOT, "tools", "schema.sql")
FRAMES_DIR = os.path.join(ROOT, "frames")
SHEETS_DIR = os.path.join(ROOT, "sheets")
ASSIGN_DIR = os.path.join(ROOT, "assignments")
FONT = os.environ.get("EDIT_FONT", r"<拉丁字体文件，例如 consolab.ttf 的绝对路径>")
# 中文字体只在少数 PIL 直读的场景用到（drawtext 请用 fontconfig 家族名，见 SKILL.md T8/T9）
CJK_FONT = os.environ.get("EDIT_CJK_FONT", r"<中文字体文件绝对路径>")

CST = timezone(timedelta(hours=8))

# 本项目覆盖的拍摄日（YYYYMMDD）——入库/盘点用，换项目时按需替换
DAYS = os.environ.get("EDIT_DAYS", "").split(",") if os.environ.get("EDIT_DAYS") else []

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def connect(db=DB, readonly=False):
    if readonly:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    else:
        con = sqlite3.connect(db, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=60000")
    return con


def probe(path: str) -> dict:
    """返回单个视频文件的技术元数据。"""
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {out.stderr[:300]}")
    j = json.loads(out.stdout)
    fmt = j.get("format", {})
    tags = fmt.get("tags", {})
    v = None
    a = None
    for s in j.get("streams", []):
        if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic"):
            v = s
        if s.get("codec_type") == "audio":
            a = s
    def _f(x):
        try:
            return float(x)
        except Exception:
            return None
    fps = None
    if v and v.get("avg_frame_rate") and v["avg_frame_rate"] != "0/0":
        num, den = v["avg_frame_rate"].split("/")
        if float(den):
            fps = float(num) / float(den)
    ct = tags.get("creation_time") or (v or {}).get("tags", {}).get("creation_time")
    return {
        "duration_s": _f(fmt.get("duration")),
        "size_bytes": int(fmt.get("size") or 0),
        "width": (v or {}).get("width"),
        "height": (v or {}).get("height"),
        "fps": fps,
        "codec": (v or {}).get("codec_name"),
        "bitrate_mbps": (_f(fmt.get("bit_rate")) or 0) / 1e6,
        "has_audio": 1 if a else 0,
        "audio_kbps": (_f((a or {}).get("bit_rate")) or 0) / 1e3,
        "camera": tags.get("encoder"),
        "creation_time_utc": ct,
        "nb_frames": (v or {}).get("nb_frames"),
    }


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def iso_local(dt: datetime) -> str:
    return dt.astimezone(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def parse_utc(s: str) -> datetime:
    s = s.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def clip_nos_from_name(name: str):
    """<前缀>_<YYYYMMDDhhmmss>_<NNNN>_D.MP4 -> ('YYYYMMDD', 'NNNN')"""
    stem = os.path.splitext(os.path.basename(name))[0]
    parts = stem.split("_")
    ts = parts[1]
    return ts[:8], parts[2]
