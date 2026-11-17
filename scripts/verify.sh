#!/usr/bin/env bash
# ============================================================
# venue-radar 一键校验脚本
# ------------------------------------------------------------
# 依次执行：
#   1. Python 语法编译检查
#   2. Python 单元测试 + 数据契约 + Flask 集成测试
#   3. Node 前端逻辑测试（内置 test runner）
#   4. JavaScript 语法检查
#   5. JSON 数据可解析检查
# 用法：bash scripts/verify.sh
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY="python"
NODE="${NODE_BIN:-node}"

green() { printf '\033[32m%s\033[0m\n' "$1"; }
red()   { printf '\033[31m%s\033[0m\n' "$1"; }
step()  { printf '\n=== %s ===\n' "$1"; }

FAILED=0
run() {
  local label="$1"; shift
  step "$label"
  if "$@"; then
    green "✓ $label 通过"
  else
    red "✗ $label 失败"
    FAILED=1
  fi
}

# 0. 依赖提示（不强制安装）
if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  echo "[提示] 未检测到 Flask，Flask 集成测试会失败。请执行：pip install -r server/requirements.txt"
fi

run "Python 语法检查" "$PY" -m py_compile server/app.py server/sync.py
run "Python 测试（同步引擎/数据契约/Flask 集成）" "$PY" -m unittest discover -s tests -p 'test_*.py' -v
run "JavaScript 语法检查" "$NODE" --check assets/app.js
run "前端逻辑测试（Node test runner）" "$NODE" --test tests/js/*.test.js
run "JSON 数据校验" "$PY" -c "import json,pathlib; d=json.loads(pathlib.Path('data/venues.json').read_text(encoding='utf-8')); assert len(d['venues'])==31; print('venues.json OK:', len(d['venues']), '条')"

echo
if [ "$FAILED" -eq 0 ]; then
  green "全部校验通过 ✅"
else
  red "存在失败项，请检查上方输出"
fi
exit "$FAILED"
