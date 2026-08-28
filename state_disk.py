#!/usr/bin/env python3
"""Скачать/загрузить state.json на Bitrix Disk (для cloud-прогонов без локального диска)."""
import base64
import json
import os
import sys
import urllib.request

WEBHOOK = os.environ.get("BITRIX24_WEBHOOK_URL", "").strip().rstrip("/")
FILE_ID = os.environ.get("BITRIX_DISK_STATE_FILE_ID", "").strip()
STATE_FILE = os.environ.get("STATE_FILE", "state.json")


def call(method, params):
    body = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK + "/" + method + ".json",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def download():
    r = call("disk.file.get", {"id": FILE_ID})
    url = (r.get("result") or {}).get("DOWNLOAD_URL")
    if not url:
        print("disk.file.get: нет DOWNLOAD_URL", file=sys.stderr)
        sys.exit(1)
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    os.makedirs(os.path.dirname(os.path.abspath(STATE_FILE)) or ".", exist_ok=True)
    with open(STATE_FILE, "wb") as f:
        f.write(data)
    print(f"state скачан → {STATE_FILE}")


def upload():
    if not os.path.exists(STATE_FILE):
        print(f"нет файла {STATE_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(STATE_FILE, "rb") as f:
        content = f.read()
    name = os.path.basename(STATE_FILE) or "state.json"
    r = call(
        "disk.file.uploadversion",
        {"id": FILE_ID, "fileContent": [name, base64.b64encode(content).decode("ascii")]},
    )
    if r.get("result"):
        print(f"state залит на Disk (id={FILE_ID})")
        return
    print(json.dumps(r, ensure_ascii=False)[:500], file=sys.stderr)
    sys.exit(1)


def main():
    if not WEBHOOK or not FILE_ID:
        print("Нужны BITRIX24_WEBHOOK_URL и BITRIX_DISK_STATE_FILE_ID", file=sys.stderr)
        sys.exit(2)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "download":
        download()
    elif cmd == "upload":
        upload()
    else:
        print("usage: state_disk.py download|upload", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
