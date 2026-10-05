#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建镜像时取 sing-box 内核 —— 只用镜像里现成的 python, 不依赖 curl / apt。

优先级:
  1. /tpl/sing-box            已经是一个二进制
  2. /tpl/sing-box*.tar.gz    本地内核包 (国内可以先手动下好放进 docker/ 目录)
  3. SINGBOX_URL              显式下载地址 (可以带 gh-proxy 之类的加速前缀)
  4. GitHub release 最新版    (先去 api.github.com 问版本号)

下载走 urllib, 所以构建时的 --build-arg HTTP_PROXY/HTTPS_PROXY 会被自动使用。
装到 /sing-box (镜像里再拷到 /usr/local/bin/sing-box)。
"""
import glob
import json
import os
import platform
import shutil
import sys
import tarfile
import urllib.request

TPL = os.environ.get("TPL_DIR", "/tpl")          # 镜像里是 /tpl
DEST = os.environ.get("DEST", "/sing-box")       # 镜像里是 /sing-box
TMP = os.environ.get("TMP_TARBALL", "/tmp/sing-box.tar.gz")
VERSION = (os.environ.get("SINGBOX_VERSION") or "latest").strip() or "latest"
URL = (os.environ.get("SINGBOX_URL") or "").strip()
UA = {"User-Agent": "amaneproxy-docker-build"}


def log(msg):
    print(">>> " + msg, flush=True)


def arch_name():
    m = platform.machine().lower()
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64",
            "arm64": "arm64", "armv7l": "armv7"}.get(m, m)


def download(url, dest):
    log("下载内核: " + url)
    # urllib 会自动吃 HTTP_PROXY / HTTPS_PROXY 环境变量 (docker build --build-arg 会传进来)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    log("下载完成: %.1f MB" % (os.path.getsize(dest) / 1048576.0))


def extract(tarball, dest):
    with tarfile.open(tarball) as t:
        for m in t.getmembers():
            if m.isfile() and os.path.basename(m.name) == "sing-box":
                with t.extractfile(m) as src, open(dest, "wb") as f:
                    shutil.copyfileobj(src, f)
                os.chmod(dest, 0o755)
                log("解出内核: %s (%.1f MB)" % (dest, os.path.getsize(dest) / 1048576.0))
                return True
    return False


def latest_version():
    req = urllib.request.Request(
        "https://api.github.com/repos/SagerNet/sing-box/releases/latest", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())["tag_name"].lstrip("v")


def main() -> int:
    if os.path.isfile(os.path.join(TPL, "sing-box")):
        log("用 docker/ 里自带的 sing-box 二进制")
        shutil.copyfile(os.path.join(TPL, "sing-box"), DEST)
        os.chmod(DEST, 0o755)
        return 0

    local = sorted(glob.glob(os.path.join(TPL, "sing-box*.tar.gz")))
    if local:
        log("用 docker/ 里自带的内核包: " + local[0])
        return 0 if extract(local[0], DEST) else 1

    ver = VERSION
    if ver == "latest":
        try:
            ver = latest_version()
            log("最新版本: v" + ver)
        except Exception as e:
            ver = "1.14.2"
            log("问最新版本失败 (%s), 退回 v%s" % (e, ver))

    url = URL or ("https://github.com/SagerNet/sing-box/releases/download/v%s/"
                  "sing-box-%s-linux-%s.tar.gz" % (ver, ver, arch_name()))
    download(url, TMP)
    if not extract(TMP, DEST):
        log("包里没找到 sing-box 二进制")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
