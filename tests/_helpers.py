#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试辅助：以文件路径加载仓库中的 Python 模块，避免污染 sys.path。

被加载的模块：
  sync        —— server/sync.py（同步引擎）
  load_flask()—— server/app.py（Flask 后端，按需加载）
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "venues.json"


def load(name, relpath):
    """从 ROOT/relpath 加载模块并返回模块对象。"""
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    if spec is None or spec.loader is None:
        raise ImportError("无法加载模块: %s" % relpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 同步引擎为纯标准库实现，可在任何环境直接加载
sync = load("venue_radar_sync", "server/sync.py")

# Flask 后端按需加载，避免只跑同步测试时也要求安装 Flask
_flask_app = None


def load_flask():
    global _flask_app
    if _flask_app is None:
        _flask_app = load("venue_radar_flask_app", "server/app.py")
    return _flask_app
