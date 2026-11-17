#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
venue-radar 轻量后端（可选）
============================
纯静态部署（GitHub Pages / 任意 nginx）不需要本文件。
部署到云服务器并希望「立即更新」按钮触发真实同步时使用：

    cd server
    pip install -r requirements.txt
    python app.py                     # 默认 0.0.0.0:8787

接口：
    GET  /                     -> index.html（静态托管整个站点）
    GET  /api/venues           -> data/venues.json
    POST /api/sync             -> 触发同步（CCFDDL + 可选 MiniMax 官网抽取）后返回最新数据
"""

import json
import threading
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, send_from_directory, request

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "venues.json"

app = Flask(__name__, static_folder=None)
_sync_lock = threading.Lock()


@app.route("/")
def index():
    return send_from_directory(ROOT, "index.html")


@app.route("/assets/<path:fname>")
def assets(fname):
    return send_from_directory(ROOT / "assets", fname)


@app.route("/data/<path:fname>")
def data(fname):
    return send_from_directory(ROOT / "data", fname)


@app.route("/api/venues")
def api_venues():
    return jsonify(json.loads(DATA_FILE.read_text(encoding="utf-8")))


@app.route("/api/sync", methods=["POST"])
def api_sync():
    if not _sync_lock.acquire(blocking=False):
        return jsonify({"ok": False, "message": "已有同步任务在进行中，请稍候"}), 429
    try:
        r = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "sync.py")],
            capture_output=True, text=True, timeout=600,
        )
        ok = r.returncode == 0
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        last = (data.get("meta", {}).get("syncLog") or [{}])[-1]
        changes = last.get("changes") or []
        return jsonify({
            "ok": ok,
            "data": data,
            "changes": changes,
            "message": ("同步完成，更新 %d 条" % len(changes)) if ok
                       else ("同步脚本异常：%s" % (r.stderr or r.stdout)[-300:]),
            "log": (r.stdout or "")[-2000:],
        }), (200 if ok else 500)
    finally:
        _sync_lock.release()


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "8787"))
    host = os.environ.get("HOST", "127.0.0.1")
    print("venue-radar serving at http://%s:%d  (同步接口 POST /api/sync)" % (host, port))
    app.run(host=host, port=port, threaded=True)
