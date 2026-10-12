"""本地音乐 API（v0.2 形态）客户端：写谱 / 渲染 / 扒谱 / 谱面工具 / job 轮询。

服务自解释：`python yue2_client.py doc` 直接把服务根路径的文档打出来，
`examples` 返回**可直接回发的示例 body**。统一入口默认 `http://127.0.0.1:8100`；
`/v1/transcribe` 由这个入口转发给服务自己的扒谱后端，所以外部只需要知道一个地址。

换项目要改的只有三样：
  1. **服务地址** —— 环境变量 `YUE2_BASE`（默认回环，远端部署时覆盖）；
  2. **鉴权** —— 环境变量 `YUE2_API_KEY`（为空就不带 `X-API-Key` 头；`/` 与 `/health` 免 key）；
  3. **模型 / 端点名** —— 下面这些路径是**服务侧的契约名**，换一套服务要按它自己的文档改名
     （先跑 `doc` 看 `endpoints`）：`/v1/plans`、`/v1/songs`、`/v1/covers`、`/v1/transcribe`、
     `/v1/tools/abc/{inspect,strip-chords,compare}`、`/v1/jobs/{id}[/files|/file/{name}]`、
     `/v1/admin/unload`。
只依赖 Python 3 标准库（urllib + json + uuid），不需要 requests。

用法示例:
  python yue2_client.py health
  python yue2_client.py doc | examples
  python yue2_client.py plans  --style style.txt [--cot full|melody] [--sync]
  python yue2_client.py songs  --style style.txt --abc a.abc [--seconds 90] [--seed N]
  python yue2_client.py transcribe --audio a.mp3 [--task full] [--max-seconds 90]
  python yue2_client.py inspect --abc a.abc
  python yue2_client.py strip-chords --abc a.abc | compare --abc a.abc --abc2 b.abc
  python yue2_client.py jobs  <job_id> [--interval 3]
  python yue2_client.py files <job_id> [--via jobs|transcribe]
  python yue2_client.py get   <job_id> <name> [--out local_path] [--via jobs|transcribe]
  python yue2_client.py unload [--transcriber]

注：
  * `--style` 既接受**文件路径**也接受**字面串**（文件存在就读文件）。
  * 长任务**不要**加 `--sync`（`?wait=1` 的长连接会被中间的反向代理掐掉，
    报 `RemoteDisconnected`）：默认就是异步提交 + 轮询 `/v1/jobs/{id}`。
  * 扒谱产物（`key.lab` / `chord.lab` / `melody_instrumental.lab` 等）走
    `/v1/transcribe/{id}/file/{name}`，**不在 `/v1/jobs` 下** —— 取它们要加 `--via transcribe`。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("YUE2_BASE", "http://127.0.0.1:8100")
KEY = os.environ.get("YUE2_API_KEY", "")
TIMEOUT = int(os.environ.get("YUE2_TIMEOUT", "600"))
UA = "yue2-client/0.1"


def _req(path, data=None, ctype=None, method=None):
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("User-Agent", UA)
    if KEY and path not in ("/", "/health"):
        r.add_header("X-API-Key", KEY)
    if ctype:
        r.add_header("Content-Type", ctype)
    return r


class ApiError(RuntimeError):
    """HTTP 4xx/5xx，带服务端返回的 detail（里面有 usage 提示）。"""


def call(path, body=None, wait=False, raw=False, method=None):
    """POST/GET 一个接口。wait=True 时加 ?wait=1 同步等结果。

    出错时把服务端返回的 body 一起抛出来——API 的 4xx/422 里带 usage/detail
    （通常写着 `see GET / for usage / example payloads`），是排查参数问题最有用的信息。
    """
    if wait:
        path += ("&" if "?" in path else "?") + "wait=1"
    data, ctype = None, None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        ctype = "application/json"
    try:
        with urllib.request.urlopen(_req(path, data, ctype, method), timeout=TIMEOUT) as f:
            b = f.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:1500]
        raise ApiError(f"HTTP {e.code} {path}\n{detail}") from None
    return b if raw else json.loads(b.decode("utf-8", "replace"))


def _multipart(fields, files):
    """files: {字段名: (文件名, bytes)}。上传音频的字段名必须是 `file`。"""
    bd = "----yue2client" + uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        if v is None:
            continue
        out += (f"--{bd}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n").encode("utf-8")
    for k, (fn, blob) in files.items():
        out += (f"--{bd}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                f"filename=\"{fn}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                ).encode("utf-8")
        out += blob + b"\r\n"
    out += f"--{bd}--\r\n".encode("utf-8")
    return out, f"multipart/form-data; boundary={bd}"


def upload(path, fields, audio_path, audio_field="file", wait=False):
    """multipart 上传本地音频。"""
    if wait:
        path += ("&" if "?" in path else "?") + "wait=1"
    blob = open(audio_path, "rb").read()
    body, ctype = _multipart(fields, {audio_field: (os.path.basename(audio_path), blob)})
    try:
        with urllib.request.urlopen(_req(path, body, ctype), timeout=TIMEOUT) as f:
            return json.loads(f.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:1500]
        raise ApiError(f"HTTP {e.code} {path}\n{detail}") from None


def wait_job(job, interval=3.0, timeout=None):
    """如果返回的是 202 + job，就轮询到 done。

    两件事必须这么写：
      1. **404 要重试**——刚提交时 job 可能还没进注册表；
      2. `done` / `done_truncated` 都算成功（`done_truncated` = 撞了 seconds/max_tokens 上限，
         不是故障），只有 `failed` 才是失败。
    """
    if not isinstance(job, dict) or job.get("status") in ("done", "done_truncated", "failed"):
        return job
    jid = job.get("job_id") or job.get("id")
    if not jid:
        return job
    t0, limit, miss = time.time(), timeout or TIMEOUT, 0
    while time.time() - t0 < limit:
        try:
            j = call(f"/v1/jobs/{jid}")
        except ApiError as e:
            if "404" not in str(e) or miss > 20:
                raise
            miss += 1
            time.sleep(interval)
            continue
        if j.get("status") in ("done", "done_truncated", "failed"):
            return j
        time.sleep(interval)
    raise SystemExit(f"任务 {jid} 超时（{limit}s）")


def job_root(via):
    """产物下载的路径前缀：普通 job 在 /v1/jobs，扒谱产物在 /v1/transcribe。"""
    return "transcribe" if via == "transcribe" else "jobs"


def download(job_id, name, out, via="jobs"):
    b = call(f"/v1/{job_root(via)}/{job_id}/file/{name}", raw=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, "wb").write(b)
    return out


def _txt(v):
    """--style / --abc / --lyrics：文件存在就读文件，否则当字面串。"""
    if v and os.path.exists(v):
        return open(v, encoding="utf-8").read()
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("arg", nargs="?", help="job_id")
    ap.add_argument("name", nargs="?", help="要下载的产物名，如 native/audio.flac")
    ap.add_argument("--style")
    ap.add_argument("--lyrics")
    ap.add_argument("--abc")
    ap.add_argument("--abc2")
    ap.add_argument("--audio")
    ap.add_argument("--out")
    ap.add_argument("--via", default="jobs", choices=["jobs", "transcribe"],
                    help="产物路径前缀：普通 job 用 jobs，扒谱产物用 transcribe")
    ap.add_argument("--task", default="full")
    ap.add_argument("--cot", default=None)
    ap.add_argument("--seconds", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=0)
    ap.add_argument("--max-seconds", type=int, default=0)
    ap.add_argument("--seed", type=int, default=831001)
    ap.add_argument("--interval", type=float, default=3.0, help="轮询间隔秒（长任务用 6）")
    ap.add_argument("--instrumental", action="store_true")
    ap.add_argument("--transcriber", action="store_true",
                    help="unload 时连扒谱后端一起卸载（释放显存）")
    ap.add_argument("--sync", action="store_true", help="加 ?wait=1 同步等待（长任务别用）")
    a = ap.parse_args()
    c = a.cmd

    if c == "health":
        print(json.dumps(call("/health", method="GET"), ensure_ascii=False, indent=1))
    elif c in ("doc", "docs"):
        sys.stdout.write(call("/", method="GET", raw=True).decode("utf-8", "replace"))
    elif c == "examples":
        print(json.dumps(call("/v1/examples", method="GET"), ensure_ascii=False, indent=1))
    elif c == "plans":
        body = {"style": _txt(a.style), "cot": a.cot or "full", "seed": a.seed}
        if a.lyrics:
            body["lyrics"] = _txt(a.lyrics)
        print(json.dumps(wait_job(call("/v1/plans", body, wait=a.sync), interval=a.interval),
                         ensure_ascii=False, indent=1)[:3000])
    elif c == "songs":
        body = {"style": _txt(a.style), "seed": a.seed, "instrumental": a.instrumental or not a.lyrics}
        for k, v in (("lyrics", _txt(a.lyrics)), ("abc", _txt(a.abc))):
            if v:
                body[k] = v
        if a.cot:
            body["cot"] = a.cot
        if a.seconds:
            body["seconds"] = a.seconds
        if a.max_tokens:
            body["max_tokens"] = a.max_tokens
        print(json.dumps(wait_job(call("/v1/songs", body, wait=a.sync), interval=a.interval),
                         ensure_ascii=False, indent=1)[:3000])
    elif c == "cover":
        f = {"style": _txt(a.style), "task": a.task, "cot": a.cot or "melody",
             "instrumental": "false" if not a.instrumental else "true",
             "transcribe_max_seconds": a.max_seconds or None, "lyrics": _txt(a.lyrics)}
        print(json.dumps(wait_job(upload("/v1/covers", f, a.audio, wait=a.sync),
                                  interval=a.interval), ensure_ascii=False, indent=1)[:3000])
    elif c == "transcribe":
        f = {"task": a.task, "max_seconds": a.max_seconds or None}
        print(json.dumps(wait_job(upload("/v1/transcribe", f, a.audio, wait=a.sync),
                                  interval=a.interval), ensure_ascii=False, indent=1)[:4000])
    elif c in ("inspect", "strip-chords", "compare"):
        if c == "compare":
            body = {"before": _txt(a.abc), "after": _txt(a.abc2)}
        else:
            body = {"abc": _txt(a.abc)}
        print(json.dumps(call(f"/v1/tools/abc/{c}", body), ensure_ascii=False, indent=1)[:4000])
    elif c == "jobs":
        print(json.dumps(call(f"/v1/jobs/{a.arg}", method="GET"),
                         ensure_ascii=False, indent=1)[:4000])
    elif c == "files":
        print(json.dumps(call(f"/v1/{job_root(a.via)}/{a.arg}/files", method="GET"),
                         ensure_ascii=False, indent=1))
    elif c == "get":
        if not a.name:
            raise SystemExit("用法: get <job_id> <name> [--out local_path] [--via jobs|transcribe]")
        out = a.out or os.path.basename(a.name)
        print("->", download(a.arg, a.name, out, via=a.via))
    elif c == "unload":
        p = "/v1/admin/unload" + ("?transcriber=true" if a.transcriber else "")
        print(json.dumps(call(p, method="POST"), ensure_ascii=False))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
