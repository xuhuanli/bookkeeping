#!/bin/bash
# Compatible with the Bash 3.2 shipped on Intel Macs.
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "$0")" && pwd -P)"
cd "$TASK_ROOT"
TASK_ARCH="$(/usr/bin/uname -m)"
case "$TASK_ARCH" in
  x86_64) TASK_UV_TARGET="x86_64-apple-darwin" ;;
  arm64) TASK_UV_TARGET="aarch64-apple-darwin" ;;
  *) printf '不支持当前处理器：%s\n' "$TASK_ARCH"; exit 1 ;;
esac
TASK_RUNTIME="$TASK_ROOT/.runtime/$TASK_ARCH"
TASK_LOCK="$TASK_RUNTIME/setup.lock"
TASK_LOCK_OWNED=0
TASK_INTERRUPTED=0
mkdir -p "$TASK_RUNTIME/downloads" "$TASK_RUNTIME/bin"
finish() {
  local task_status=$?
  if [ "$TASK_LOCK_OWNED" = 1 ]; then
    rm -f "$TASK_LOCK/pid"
    rmdir "$TASK_LOCK" 2>/dev/null || true
  fi
  if [ "$TASK_INTERRUPTED" = 1 ]; then
    printf '\n操作已停止。\n'
  elif [ "$task_status" -ne 0 ]; then
    printf '\n启动未完成，请查看上面的错误。首次准备运行环境需要联网。\n'
    if [ -t 0 ] && [ "${BOOKKEEPING_NO_PAUSE:-0}" != 1 ]; then
      read -r -p '按回车关闭此窗口…' _task_reply || true
    fi
  fi
}
trap finish EXIT
trap 'TASK_INTERRUPTED=1; exit 130' INT TERM HUP
printf '\n针线小账 · 一键启动\n电脑架构：%s\n项目目录：%s\n\n' "$TASK_ARCH" "$TASK_ROOT"
TASK_WAIT=0
while ! mkdir "$TASK_LOCK" 2>/dev/null; do
  TASK_OWNER="$(cat "$TASK_LOCK/pid" 2>/dev/null || true)"
  if [[ "$TASK_OWNER" =~ ^[0-9]+$ ]] && ! kill -0 "$TASK_OWNER" 2>/dev/null; then
    rm -f "$TASK_LOCK/pid"
    rmdir "$TASK_LOCK" 2>/dev/null || true
    continue
  fi
  if [ "$TASK_WAIT" -eq 0 ]; then printf '另一窗口正在准备环境，等待准备完成…\n'; fi
  if [ "$TASK_WAIT" -ge 300 ]; then printf '等待超时，请关闭其他启动窗口后重试。\n'; exit 1; fi
  sleep 1
  TASK_WAIT=$((TASK_WAIT + 1))
done
TASK_LOCK_OWNED=1
printf '%s\n' "$$" > "$TASK_LOCK/pid"

TASK_MACOS="$(/usr/bin/sw_vers -productVersion)"
printf 'macOS 版本：%s\n' "$TASK_MACOS"
TASK_MACOS_MAJOR="${TASK_MACOS%%.*}"
if [ "$TASK_MACOS_MAJOR" -lt 12 ]; then
  printf '旧版 macOS：检查电脑已有的兼容 Python…\n'
  TASK_NATIVE_PYTHON=""
  for task_candidate in "$TASK_ROOT/.venv/bin/python" /usr/local/bin/python3.12 /usr/local/bin/python3.13 /usr/local/bin/python3.11 /usr/local/bin/python3.10 /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
    if "$task_candidate" -c 'import platform,sys; assert sys.version_info >= (3,10); assert platform.machine()==sys.argv[1]' "$TASK_ARCH" >/dev/null 2>&1; then
      TASK_NATIVE_PYTHON="$task_candidate"
      break
    fi
  done
  if [ -z "$TASK_NATIVE_PYTHON" ]; then
    printf '当前系统为 macOS %s，缺少 Python 3.10 以上版本。\n' "$TASK_MACOS"
    printf '请先安装适合当前系统的 Python，再双击此文件。下载地址：\nhttps://www.python.org/downloads/macos/\n'
    exit 1
  fi
  TASK_ENV="$TASK_RUNTIME/venv"
  TASK_PYTHON="$TASK_ENV/bin/python"
  if ! "$TASK_PYTHON" -c 'import platform,sys; from pathlib import Path; assert sys.version_info >= (3,10); assert platform.machine()==sys.argv[1]; assert Path(sys.prefix).resolve()==Path(sys.argv[2]).resolve()' "$TASK_ARCH" "$TASK_ENV" >/dev/null 2>&1; then
    if [ -e "$TASK_ENV" ]; then mv "$TASK_ENV" "$TASK_RUNTIME/venv-old-$(date +%Y%m%d-%H%M%S)-$$"; fi
    "$TASK_NATIVE_PYTHON" -m venv "$TASK_ENV"
  fi
  TASK_REQUIREMENTS_HASH="$(/usr/bin/shasum -a 256 requirements.txt | awk '{print $1}')"
  if [ "$TASK_REQUIREMENTS_HASH" != "$(cat "$TASK_RUNTIME/requirements.sha256" 2>/dev/null || true)" ] || ! "$TASK_PYTHON" -c 'import fastapi,uvicorn,multipart,PIL,openpyxl' >/dev/null 2>&1; then
    "$TASK_PYTHON" -m pip install --disable-pip-version-check --only-binary :all: -r requirements.txt
    printf '%s\n' "$TASK_REQUIREMENTS_HASH" > "$TASK_RUNTIME/requirements.sha256"
  fi
  rm -f "$TASK_LOCK/pid"
  rmdir "$TASK_LOCK"
  TASK_LOCK_OWNED=0
  "$TASK_PYTHON" "$TASK_ROOT/scripts/launcher.py" "$@"
  exit $?
fi

# uv on Monterey expects realpath; a project-local helper avoids system changes.
if ! command -v realpath >/dev/null 2>&1; then
  cp "$TASK_ROOT/scripts/realpath.pl" "$TASK_RUNTIME/bin/realpath"
  chmod +x "$TASK_RUNTIME/bin/realpath"
fi
export PATH="$TASK_RUNTIME/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export UV_PYTHON_INSTALL_DIR="$TASK_RUNTIME/python"
export UV_CACHE_DIR="$TASK_RUNTIME/cache"
export UV_PYTHON_BIN_DIR="$TASK_RUNTIME/bin"
export UV_LINK_MODE=copy
export UV_NO_MODIFY_PATH=1
TASK_UV_VERSION="0.13.0"
TASK_UV_DIR="$TASK_RUNTIME/uv-$TASK_UV_VERSION"
TASK_UV="$TASK_UV_DIR/$([ "$TASK_ARCH" = x86_64 ] && printf 'uv-x86_64-apple-darwin' || printf 'uv-aarch64-apple-darwin')/uv"
if ! "$TASK_UV" --version >/dev/null 2>&1; then
  printf '首次准备：下载项目专用的 Python 环境管理器…\n'
  TASK_ARCHIVE="uv-$TASK_UV_TARGET.tar.gz"
  TASK_BASE="https://github.com/astral-sh/uv/releases/download/$TASK_UV_VERSION"
  curl -fL --retry 2 --connect-timeout 20 --max-time 300 "$TASK_BASE/$TASK_ARCHIVE" -o "$TASK_RUNTIME/downloads/$TASK_ARCHIVE.part"
  curl -fsSL --retry 2 --connect-timeout 20 --max-time 60 "$TASK_BASE/$TASK_ARCHIVE.sha256" -o "$TASK_RUNTIME/downloads/$TASK_ARCHIVE.sha256"
  TASK_EXPECTED="$(awk 'NR==1 {print $1}' "$TASK_RUNTIME/downloads/$TASK_ARCHIVE.sha256")"
  TASK_ACTUAL="$(/usr/bin/shasum -a 256 "$TASK_RUNTIME/downloads/$TASK_ARCHIVE.part" | awk '{print $1}')"
  if ! [[ "$TASK_EXPECTED" =~ ^[0-9a-f]{64}$ ]] || [ "$TASK_EXPECTED" != "$TASK_ACTUAL" ]; then
    printf '下载校验失败，请重新双击启动。\n'; exit 1
  fi
  mkdir -p "$TASK_UV_DIR"
  tar -xzf "$TASK_RUNTIME/downloads/$TASK_ARCHIVE.part" -C "$TASK_UV_DIR"
  mv "$TASK_RUNTIME/downloads/$TASK_ARCHIVE.part" "$TASK_RUNTIME/downloads/$TASK_ARCHIVE"
fi
printf '检查项目专用 Python 3.12…\n'
if ! TASK_BASE_PYTHON="$("$TASK_UV" python find --managed-python --no-python-downloads --no-project 3.12 2>/dev/null)"; then
  "$TASK_UV" python install 3.12 --no-bin
  TASK_BASE_PYTHON="$("$TASK_UV" python find --managed-python --no-project 3.12)"
fi
TASK_ENV="$TASK_RUNTIME/venv"
TASK_PYTHON="$TASK_ENV/bin/python"
if ! "$TASK_PYTHON" -c 'import platform,sys; from pathlib import Path; assert platform.machine()==sys.argv[1]; assert sys.version_info[:2]==(3,12); assert Path(sys.prefix).resolve()==Path(sys.argv[2]).resolve()' "$TASK_ARCH" "$TASK_ENV" >/dev/null 2>&1; then
  if [ -e "$TASK_ENV" ]; then mv "$TASK_ENV" "$TASK_RUNTIME/venv-old-$(date +%Y%m%d-%H%M%S)-$$"; fi
  "$TASK_UV" venv --python "$TASK_BASE_PYTHON" "$TASK_ENV"
fi
TASK_REQUIREMENTS_HASH="$(/usr/bin/shasum -a 256 requirements.txt | awk '{print $1}')"
TASK_SAVED_HASH="$(cat "$TASK_RUNTIME/requirements.sha256" 2>/dev/null || true)"
if [ "$TASK_REQUIREMENTS_HASH" != "$TASK_SAVED_HASH" ] || ! "$TASK_PYTHON" -c 'import fastapi,uvicorn,multipart,PIL,openpyxl; from zoneinfo import ZoneInfo; ZoneInfo("Asia/Shanghai")' >/dev/null 2>&1; then
  printf '安装 / 更新后端依赖…\n'
  "$TASK_UV" pip install --python "$TASK_PYTHON" --only-binary :all: -r "$TASK_ROOT/requirements.txt"
  printf '%s\n' "$TASK_REQUIREMENTS_HASH" > "$TASK_RUNTIME/requirements.sha256"
fi
rm -f "$TASK_LOCK/pid"
rmdir "$TASK_LOCK"
TASK_LOCK_OWNED=0
"$TASK_PYTHON" "$TASK_ROOT/scripts/launcher.py" "$@"
