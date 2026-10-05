#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amane 代理调度器 · 安装脚本

用法:
    python setup.py                      # 装到默认目录 (%LOCALAPPDATA%\\AmaneProxy / ~/.local/share/AmaneProxy)
    python setup.py --root D:\\AmaneProxy --proxy http://127.0.0.1:1080

做四件事:
    1. 复制管理器 / 面板 (Windows 上还复制启停脚本 / 托盘图标) 到安装目录
    2. 没有 sing-box 内核就按平台下载官方 release (windows-amd64 / linux-amd64|arm64, 走 --proxy 指定的本地代理)
    3. 从 nekoray/nekobox 的 profiles 里读出服务器凭据, 生成 servers.json
       (读不到就写模板, 之后在面板的「出口管理」里填)
    4. 打印后续步骤 (装自启 / 接 Amane)

想用 Docker 就不用跑这个脚本: 见 README 第 3 节 / Dockerfile / docker-compose.yml。
"""
import argparse
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"
# arch 名和 sing-box release 资产名一致 (amd64 / arm64 / armv7)
ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64",
        "arm64": "arm64", "armv7l": "armv7"}.get(platform.machine().lower(), "amd64")
# 管理器 / 面板是跨平台的; 剩下的脚本和托盘图标是 Windows 专用
FILES = ["amaneproxy.py", "panel.html"]
if IS_WIN:
    FILES += ["start.vbs", "ensure.ps1", "stop.ps1", "status.ps1",
              "install-autostart.ps1", "uninstall-autostart.ps1",
              "bin/tray_on.ico", "bin/tray_off.ico", "bin/tray_err.ico"]
SB_URL = ("https://github.com/SagerNet/sing-box/releases/latest/download/sing-box-{ver}-windows-amd64.zip"
          if IS_WIN else
          "https://github.com/SagerNet/sing-box/releases/latest/download/sing-box-{ver}-linux-%s.tar.gz" % ARCH)
NEKO_PROFILES = [Path(os.environ.get("APPDATA") or "_") / "nekoray" / "config" / "profiles",
                 Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "nekoray" / "config" / "profiles"]


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
    exe = root / "bin" / ("sing-box.exe" if IS_WIN else "sing-box")
    if exe.exists():
        print("已存在内核:", exe)
        return
    (root / "bin").mkdir(parents=True, exist_ok=True)
    url = latest_singbox_url(proxy)
    if not url:
        print("拿不到最新版本号, 尝试 latest/download 直链")
        url = SB_URL.format(ver="1.14.2")
    tmp = Path(tempfile.mkdtemp()) / ("sb.zip" if IS_WIN else "sb.tar.gz")
    download(url, tmp, proxy)
    if IS_WIN:
        with zipfile.ZipFile(tmp) as z:
            for name in z.namelist():
                base = os.path.basename(name)
                if base in ("sing-box.exe", "libcronet.dll", "LICENSE"):
                    with z.open(name) as src, open(root / "bin" / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    print("解出", base)
    else:
        with tarfile.open(tmp) as t:
            for m in t.getmembers():
                if m.isfile() and os.path.basename(m.name) == "sing-box":
                    with t.extractfile(m) as src, open(exe, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    print("解出 bin/sing-box")
                    break
        if exe.exists():
            os.chmod(exe, 0o755)
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
            {"id": "jp", "cc": "jp", "label": "日本 · shadowsocks",
             "kind": "socks", "server": "127.0.0.1", "port": 1080, "version": "5",
             "note": "本地 SSR/SS 客户端端口; 若节点是 SSR(auth_chain_a) 就填客户端端口"},
            {"id": "kr", "cc": "kr", "label": "韩国 · hysteria2", "kind": "hysteria2",
             "server": "", "port": 0, "sni": "", "insecure": False, "password": ""},
            {"id": "us", "cc": "us", "label": "美国 · hysteria2", "kind": "hysteria2",
             "server": "", "port": 0, "sni": "", "insecure": True, "password": ""},
        ]
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"servers": servers}, f, ensure_ascii=False, indent=2)
    print("已写:", target, "->", [s["id"] for s in servers])


def main() -> int:
    ap = argparse.ArgumentParser()
    if os.environ.get("AMANEPROXY_ROOT"):
        default_root = Path(os.environ["AMANEPROXY_ROOT"]).expanduser()
    elif IS_WIN:
        default_root = Path(os.environ.get("LOCALAPPDATA", ".")) / "AmaneProxy"
    else:
        default_root = Path.home() / ".local" / "share" / "AmaneProxy"
    ap.add_argument("--root", default=str(default_root),
                    help="安装目录 (默认 %s)" % default_root)
    ap.add_argument("--proxy", default="http://127.0.0.1:1080", help="下载内核用的本地代理, 留空=直连")
    ap.add_argument("--skip-kernel", action="store_true")
    args = ap.parse_args()

    root = Path(args.root)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    for name in FILES:
        src = HERE / name
        if src.exists():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, root / name)
            print("复制", name)
    if not args.skip_kernel:
        install_singbox(root, args.proxy or None)
    write_servers(root)

    if IS_WIN:
        print("""
下一步:
  1) 启动:      wscript "%(root)s\\start.vbs"
  2) 面板:      http://127.0.0.1:18111    (总览里确认出口都"可用", 出口 IP 是预期的国家)
  3) 接入 Amane: 面板 -> Amane 集成 -> 「让 Amane 走本调度器」
  4) 开机自启:  powershell -ExecutionPolicy Bypass -File "%(root)s\\install-autostart.ps1"
""" % {"root": root})
    else:
        print("""
下一步:
  1) 面板:      http://127.0.0.1:18111    (总览里确认出口都"可用", 出口 IP 是预期的国家)
  2) 接入 Amane: 面板 -> Amane 集成 -> 「让 Amane 走本调度器」
  3) 常驻运行:  python3 "%(root)s/amaneproxy.py" --no-tray
     或者用 Docker (镜像自带内核 + Python): docker compose up -d   —— 见 README 第 3 节
""" % {"root": root})
    return 0


if __name__ == "__main__":
    sys.exit(main())
