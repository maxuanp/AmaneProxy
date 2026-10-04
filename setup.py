#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amane 代理调度器 · 安装脚本

用法:
    python setup.py                      # 装到 %LOCALAPPDATA%\\AmaneProxy (当前目录已是安装目录时就直接就地初始化)
    python setup.py --root D:\\AmaneProxy --proxy http://127.0.0.1:1080

做四件事:
    1. 复制管理器 / 面板 / 启停脚本到安装目录
    2. 没有 sing-box 内核就下载官方 release (走 --proxy 指定的本地代理)
    3. 从 nekoray/nekobox 的 profiles 里读出服务器凭据, 生成 servers.json
       (读不到就写模板, 之后在面板的「出口管理」里填)
    4. 打印后续步骤 (装自启 / 接 Amane)
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ["amaneproxy.py", "panel.html", "start.vbs", "ensure.ps1", "stop.ps1", "status.ps1",
         "install-autostart.ps1", "uninstall-autostart.ps1",
         "bin/tray_on.ico", "bin/tray_off.ico", "bin/tray_err.ico"]
SB_URL = "https://github.com/SagerNet/sing-box/releases/latest/download/sing-box-{ver}-windows-amd64.zip"
NEKO_PROFILES = [Path(os.environ.get("APPDATA", "")) / "nekoray" / "config" / "profiles",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "nekoray" / "config" / "profiles"]


def latest_singbox_url(proxy: str | None) -> str:
    api = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"
    try:
        with urllib.request.urlopen(api, timeout=25) as r:
            tag = json.loads(r.read().decode())["tag_name"]
        return SB_URL.format(ver=tag.lstrip("v"))
    except Exception:
        return ""   # 交给 GitHub 的 latest/download 重定向


def download(url: str, dest: Path, proxy: str | None) -> None:
    opener = urllib.request.build_opener()
    if proxy:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    print("下载 sing-box ...", url)
    with opener.open(url, timeout=180) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def install_singbox(root: Path, proxy: str | None) -> None:
    exe = root / "bin" / "sing-box.exe"
    if exe.exists():
        print("已存在内核:", exe)
        return
    (root / "bin").mkdir(parents=True, exist_ok=True)
    url = latest_singbox_url(proxy)
    if not url:
        print("拿不到最新版本号, 尝试 latest/download 直链")
        url = "https://github.com/SagerNet/sing-box/releases/latest/download/sing-box-1.14.2-windows-amd64.zip"
    tmp = Path(tempfile.mkdtemp()) / "sb.zip"
    download(url, tmp, proxy)
    with zipfile.ZipFile(tmp) as z:
        for name in z.namelist():
            base = os.path.basename(name)
            if base in ("sing-box.exe", "libcronet.dll", "LICENSE"):
                with z.open(name) as src, open(root / "bin" / base, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print("解出", base)
    try:
        print(subprocess.run([str(exe), "version"], capture_output=True, text=True, timeout=20).stdout.splitlines()[0])
    except Exception as e:
        print("内核自检失败:", e)


def read_profiles() -> dict | None:
    """从 nekoray/nekobox profiles 里取 hysteria2 / shadowsocks 服务器。"""
    for d in NEKO_PROFILES:
        if not d or not d.is_dir():
            continue
        beans = {}
        for f in sorted(d.glob("*.json")):
            try:
                with io.open(f, encoding="utf-8") as fh:
                    obj = json.load(fh)
            except Exception:
                continue
            t, bean = obj.get("type"), obj.get("bean") or {}
            if t == "hysteria2":
                beans["hy2:" + bean.get("name", f.stem)] = {
                    "kind": "hysteria2", "server": bean.get("addr"), "port": int(bean.get("port") or 0),
                    "sni": bean.get("sni") or "", "insecure": bool(bean.get("allowInsecure")),
                    "password": bean.get("password") or "", "label": bean.get("name") or f.stem,
                }
        if beans:
            print("从 %s 读到 %d 个服务器" % (d, len(beans)))
            return beans
    return None


def write_servers(root: Path) -> None:
    target = root / "servers.json"
    if target.exists():
        print("servers.json 已存在, 保留不动:", target)
        return
    found = read_profiles() or {}
    servers = []
    for s in found.values():
        lab = s.pop("label")
        cc = "kr" if "韩" in lab or "korea" in lab.lower() else ("us" if ("美" in lab or "us" in lab.lower()) else "jp")
        servers.append({"id": lab[:12], "cc": cc, "label": lab, **s})
    if not servers:
        servers = [
            {"id": "jp", "cc": "jp", "label": "示例出口 · 本机代理客户端", "kind": "socks",
             "server": "127.0.0.1", "port": 1080, "version": "5",
             "note": "示例出口: 本机 1080 端口的 socks5/http 代理。在面板「出口管理」里改成自己的节点。"},
        ]
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"servers": servers}, f, ensure_ascii=False, indent=2)
    print("已写:", target, "->", [s["id"] for s in servers])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(os.environ.get("LOCALAPPDATA", ".")) / "AmaneProxy"))
    ap.add_argument("--proxy", default="http://127.0.0.1:1080", help="下载内核用的本地代理, 留空=直连")
    ap.add_argument("--skip-kernel", action="store_true")
    args = ap.parse_args()

    root = Path(args.root)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    for name in FILES:
        src = HERE / name
        dst = root / name
        if src.exists() and src.resolve() != dst.resolve():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print("复制", name)
    if not args.skip_kernel:
        install_singbox(root, args.proxy or None)
    write_servers(root)

    print("""
下一步:
  1) 启动:      wscript "%(root)s\\start.vbs"
  2) 面板:      http://127.0.0.1:18111    (总览 -> 出口管理 里填你自己的节点)
  3) 接入 Amane: 面板 -> Amane 集成 -> 「让 Amane 走本调度器」
  4) 开机自启:  powershell -ExecutionPolicy Bypass -File "%(root)s\\install-autostart.ps1"
""" % {"root": root})
    return 0


if __name__ == "__main__":
    sys.exit(main())
