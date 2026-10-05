#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Amane 代理调度器 · amaneproxy.py v1.0.0
=======================================================================
给 Amane 内置一个「按目标网站自动切换代理」的本地代理客户端。

为什么不是 Amane 插件: 插件 API v1 只开放「影片元数据来源 / 播放源」两类钩子,
既拿不到主机的网络栈, 也不能改配置 (docs/dev/plugins.md 明确不支持自定义 API 路由)。
Amane 的网络出口只有一个全局开关 `network.proxy`, 所以正确做法是:
    本机跑一个分流代理 (sing-box 内核) -> 把 Amane 的 network.proxy 指向它。
面板会替你把这一处配置写好, 对 Amane 而言就是"内置"。

它做什么:
  1. 一台 sing-box 实例, 监听 127.0.0.1:<proxy_port> (socks5 + http 混合入口)
  2. 多个上游出口 (日本 shadowsocks / 韩国 hysteria2 / 美国 hysteria2 ...)
  3. 按域名分流: 日本站点 -> 日本出口, 欧美站点 -> 美国出口, 韩国站点 -> 韩国出口,
     其余走默认出口(可选 自动选最快 / 直连 / 指定国家)
  4. 每 <health_interval> 秒探测每个出口的出口 IP / 国家 / 延迟; 主出口挂了自动切到
     健康备选 (sing-box selector + clash API 热切换, 不重启), 恢复后自动切回
  5. 本地面板 http://127.0.0.1:<panel_port>: 状态 / 分流规则 / 出口切换 / Amane 一键接入 / 日志

命令行:
  python amaneproxy.py            常驻运行 (面板 + 代理)
  python amaneproxy.py --stop     停止 (含 sing-box)
  python amaneproxy.py --status   查看状态
  python amaneproxy.py --once     只构建配置并启动, 不占终端(调试用: --once --verbose)
  python amaneproxy.py --no-tray  不显示系统托盘图标

托盘图标 (Windows): 平时是 pythonw 无窗口运行, 托盘就是唯一的常驻入口。
  蓝 双向箭头 = 内核在跑 · 灰 = 已停止 · 红 = 启动失败; 左键打开面板, 右键出菜单。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.4.0"
APP_DIR = Path(__file__).resolve().parent          # 代码/资源目录 (Docker 镜像里 = /app)
# 数据目录: 配置 / 规则 / 日志 / pid 都写这里。
# Docker 里设 AMANEPROXY_HOME=/data 并挂成卷, 升级镜像不会丢配置。
ROOT = Path(os.environ.get("AMANEPROXY_HOME") or APP_DIR).resolve()
PANEL_HTML = next((p for p in (APP_DIR / "panel.html", ROOT / "panel.html") if p.is_file()),
                  APP_DIR / "panel.html")


def _find_singbox() -> Path:
    """找内核: 环境变量 AMANEPROXY_SINGBOX > 代码目录/数据目录下的 bin/ > PATH。

    Windows 上是 bin\\sing-box.exe; Linux/Docker 上是 bin/sing-box (或 /usr/local/bin/sing-box)。
    """
    env = os.environ.get("AMANEPROXY_SINGBOX")
    if env:
        return Path(env)
    for cand in (APP_DIR / "bin" / "sing-box.exe", APP_DIR / "bin" / "sing-box",
                 ROOT / "bin" / "sing-box.exe", ROOT / "bin" / "sing-box"):
        if cand.is_file():
            return cand
    found = shutil.which("sing-box")
    if found:
        return Path(found)
    return APP_DIR / "bin" / ("sing-box.exe" if os.name == "nt" else "sing-box")


BIN = _find_singbox()
LOGDIR = ROOT / "logs"
CONFIG_PATH = ROOT / "config.json"
SETTINGS_PATH = ROOT / "amaneproxy.json"
SERVERS_PATH = ROOT / "servers.json"
RULES_PATH = ROOT / "rules.json"
PID_PATH = ROOT / "amaneproxy.pid"
SB_PID_PATH = ROOT / "singbox.pid"

COUNTRY_NAMES = {"jp": "日本", "kr": "韩国", "us": "美国", "hk": "香港", "sg": "新加坡", "tw": "台湾"}
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# ---------------------------------------------------------------- 默认配置

DEFAULT_SETTINGS = {
    "proxy_port": 18110,          # Amane 连这个端口 (socks5/http 混合)
    "panel_port": 18111,          # 本地面板
    "clash_port": 18112,          # sing-box 内部 clash API
    "clash_secret": "",
    # ---- 监听地址 (Docker/容器里设 0.0.0.0 才能被端口映射到; 也可用环境变量覆盖) ----
    "listen_host": "127.0.0.1",   # 代理入口   (AMANEPROXY_LISTEN_HOST)
    "panel_host": "127.0.0.1",    # 面板       (AMANEPROXY_PANEL_HOST)
    # ---- Amane 本地 API (容器里改成 http://host.docker.internal:18100) ----
    "amane_url": "http://127.0.0.1:18100",   # (AMANEPROXY_AMANE_URL)
    "amane_token_file": "",       # Amane token 文件; 留空=自动找 (容器里挂载后填 /data/amane-token)
    "default_outbound": "jp",     # auto | direct | jp | kr | us ...
    "health_interval": 60,        # 秒
    "auto_failover": True,
    "probe_url": "http://ip-api.com/json/?fields=status,message,country,countryCode,city,isp,query",
    "probe_url_fallback": "https://api.ipify.org",
    "log_level": "info",
    "amaneproxy_enabled": False,   # 是否已把 Amane 指到本调度器
    "amaneproxy_previous": None,   # 接入前的 network.proxy 原值
    "tray": True,                  # 系统托盘图标 (pythonw 无声运行时唯一的常驻入口)
    # ---- 域名同步 (自动获取站点最新域名并补规则) ----
    "sync_enabled": True,
    "sync_interval_hours": 6,
    "sync_from_amane": True,       # 从 Amane 的源配置 / 网络检测取当前域名
    "sync_follow_redirect": True,  # 跟随站点 301/302 拿到最新域名
    "sync_try_candidates": True,   # 主域名不通时试候选域名
    "sync_last": 0,
    "sync_log": [],
    "sync_max_domains": 300,
    "sync_domain_timeout": 8,      # 单个域名一次请求的超时(秒)
    "sync_max_hops": 3,            # 最多跟几跳
    "sync_workers": 16,            # 并发数
    "sync_deadline_seconds": 120,  # 一次同步的总预算(秒), 超了就下次再补
    "sync_recheck_minutes": 30,    # 最近测通的域名 N 分钟内不重测
    "sync_tune_outbound": True,    # 出口不通时, 实测其他出口并自动改走
    "sync_tune_mode": "fallback",   # fallback=只在原出口不通时改; fastest=总是选最快能通的
    "sync_tune_max": 30,           # 每次同步最多调优多少个域名
    "tuned_outbound": {},          # 域名 -> 实测调优后的出口(cc)
    "tune_never": ["dmm.co.jp", "dmm.com", "fanza.jp", "amazon.co.jp", "fujisan.co.jp"],  # 永不调优(地域敏感)
    "source_outbound": {           # 来源 -> 出口 (缺省=default_outbound)
        "theporndb": "us", "r18dev": "default", "wikipedia": "default",
    },
    "candidates": {},              # 域名 -> [候选域名, ...] (面板可编辑)
    "domain_status": {},           # 域名 -> {ok,status,ts,final,redirect,err}
}

# 多级后缀 (取根域名时要用)
MULTI_SUFFIX = {
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "ad.jp", "lg.jp", "ed.jp",
    "com.cn", "net.cn", "org.cn", "gov.cn", "co.kr", "or.kr", "com.tw", "org.tw",
    "co.uk", "org.uk", "com.au", "com.hk", "com.sg", "com.my", "com.br", "com.vn", "com.ph",
}

TWO_LEVEL = {"co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "ad.jp", "com.cn", "net.cn", "org.cn",
             "co.kr", "com.tw", "co.uk", "com.au", "com.hk", "com.sg", "com.br"}


def root_domain(host: str | None) -> str:
    """取可注册根域名: www.a.b.co.jp -> b.co.jp ; 去端口/大小写。"""
    if not host:
        return ""
    h = host.strip().lower().split(":")[0].strip(".")
    if not h:
        return ""
    parts = h.split(".")
    if len(parts) <= 2:
        return h
    last2 = ".".join(parts[-2:])
    if last2 in TWO_LEVEL:
        return ".".join(parts[-3:])
    return last2


def proxy_fetch(entry_port: int, url: str, timeout: float = 12.0, max_body: int = 8192):
    """经本机混合入口 (mixed inbound) 发一个 HTTP(S) 请求, 返回 (status, headers, body)。"""
    u = urllib.parse.urlsplit(url)
    if not u.hostname:
        raise RuntimeError("bad url: %s" % url)
    host = u.hostname
    port = u.port or (443 if u.scheme == "https" else 80)
    path = (u.path or "/") + (("?" + u.query) if u.query else "")
    s = socket.create_connection(("127.0.0.1", entry_port), timeout=timeout)
    s.settimeout(timeout)
    try:
        if u.scheme == "https":
            s.sendall(("CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\n\r\n" % (host, port, host, port)).encode())
            head = b""
            while b"\r\n\r\n" not in head:
                c = s.recv(1)
                if not c:
                    raise RuntimeError("CONNECT closed")
                head += c
            if b" 200" not in head.split(b"\r\n")[0]:
                raise RuntimeError("CONNECT failed: %s" % head.split(b"\r\n")[0][:40])
            sock = ssl.create_default_context().wrap_socket(s, server_hostname=host)
            target = path
        else:
            # 明文 HTTP 走代理必须用绝对形式请求行, 否则混合入口无法确定目标 (返回 400)
            sock = s
            target = url
        req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n"
               "Accept: */*\r\nConnection: close\r\n\r\n") % (target, host)
        sock.sendall(req.encode())
        data = b""
        while len(data) < max_body + 8192:
            try:
                chunk = sock.recv(8192)
            except Exception:
                break
            if not chunk:
                break
            data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        lines = head.decode("iso-8859-1", "replace").split("\r\n")
        try:
            status = int(lines[0].split()[1])
        except Exception:
            status = 0
        headers = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        return status, headers, body[:max_body]
    finally:
        try:
            s.close()
        except Exception:
            pass


UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")


def probe_via_socks(socks_port: int, host: str, timeout: float = 10.0):
    """经某个出口的探测入口取一次 https://host/ 的状态码与耗时; 返回 (code, ms)。
    code: 0=无响应/超时, -1=出口本身连不上。"""
    t0 = time.time()
    try:
        s = socket.create_connection(("127.0.0.1", socks_port), timeout=timeout)
        s.settimeout(timeout)
        s.sendall(b"\x05\x01\x00")
        if s.recv(2) != b"\x05\x00":
            return -1, int((time.time() - t0) * 1000)
        hb = host.encode()
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + struct.pack(">H", 443))
        rep = s.recv(4)
        if len(rep) < 2 or rep[1] != 0:
            return -1, int((time.time() - t0) * 1000)
        atyp = rep[3] if len(rep) > 3 else 1
        if atyp == 1:
            s.recv(4)
        elif atyp == 3:
            s.recv(s.recv(1)[0])
        elif atyp == 4:
            s.recv(16)
        s.recv(2)
        t = ssl.create_default_context().wrap_socket(s, server_hostname=host)
        t.sendall(("GET / HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\nAccept: */*\r\nConnection: close\r\n\r\n"
                   % (host, UA_BROWSER)).encode())
        data = b""
        while len(data) < 4096:
            try:
                c = t.recv(4096)
            except Exception:
                break
            if not c:
                break
            data += c
        try:
            code = int(data.split(b"\r\n")[0].decode("iso-8859-1", "replace").split()[1])
        except Exception:
            code = 0
        return code, int((time.time() - t0) * 1000)
    except Exception:
        return 0, int((time.time() - t0) * 1000)


def follow_redirects(entry_port: int, url: str, max_hops: int = 5, timeout: float = 12.0):
    """跟随跳转, 返回 (final_url, status, hops)。换域名的站点几乎都会留 301。"""
    cur = url
    hops = []
    status = 0
    for _ in range(max_hops):
        status, headers, _body = proxy_fetch(entry_port, cur, timeout=timeout)
        hops.append((cur, status))
        loc = headers.get("location")
        if status in (301, 302, 303, 307, 308) and loc:
            cur = urllib.parse.urljoin(cur, loc)
            continue
        break
    return cur, status, hops

DEFAULT_SERVERS = [
    # 只是个可编辑的示例出口: 默认指向本机已有的代理客户端(socks5)。
    # 启动后在面板「出口管理」里改成你自己的节点, 或点「新增出口」添日/韩/美各一台。
    # 本文件不含任何真实节点信息。
    {
        "id": "jp", "cc": "jp", "label": "示例出口 · 本机代理客户端",
        "kind": "socks", "server": "127.0.0.1", "port": 1080,
        "note": "示例出口: 指向本机 1080 端口的 socks5/http 代理(例如你已在用的代理客户端)。改成自己的节点即可。若本机没有代理客户端, 它在面板里会显示“不可用”, 属正常。",
    },
]

# 预设站点 -> 出口(国家代码)。这些是 ID 后缀匹配 (domain_suffix)
PRESET_RULES = {
    "jav": {
        "label": "日本站（片库/翻译/官方片商）→ 日本",
        "outbound": "jp",
        "suffixes": [
            "dmm.co.jp", "dmm.com", "fanza.jp", "javbus.com", "javdb.com", "javlibrary.com", "avsox.com",
            "mgstage.com", "kin8tengoku.com", "getchu.com", "giga-web.jp", "faleno.jp", "dahlia-av.jp",
            "prestige-av.com", "xcity.jp", "airav.io", "jav321.com", "freejavbt.com", "attackers.net",
            "iqqtv.com", "r18.dev", "sougouwiki.com", "av-wiki.net", "1pondo.tv", "caribbeancom.com",
            "tokyo-hot.com", "heyzo.com", "10musume.com", "pacopacomama.com", "gachinco.com", "muramura.tv",
            "heydouga.com", "h4610.com", "ideapocket.com", "s1s1s1.com", "muku.tv", "kawaiikawaii.jp",
            "moodyz.com", "premium-beauty.com", "wanzfactory.com", "madonna-av.com", "oppai-av.com",
            "dasdas.jp", "kmp.jp", "km-produce.com", "avmoo.com", "sehuatang.net", "nyahentai.com",
            "javcdn.com", "javhoo.com", "fujisan.co.jp", "amazon.co.jp",
        ],
    },
    "west": {
        "label": "欧美站 → 美国",
        "outbound": "us",
        "suffixes": [
            "theporndb.net", "iafd.com", "adultempire.com", "pornhub.com", "xvideos.com",
            "xhamster.com", "motherless.com", "txxx.com", "eporner.com", "hqporner.com",
            "beeg.com", "spankbang.com", "porntrex.com", "javhdo.com", "javmost.com",
            "theporndb.com", "erome.com", "javgg.net", "missav.com", "jable.tv",
        ],
    },
    "kr": {"label": "韩国站 → 韩国", "outbound": "kr", "suffixes": []},
}

# ---------------------------------------------------------------- 工具


def log(msg: str) -> None:
    line = "%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        with open(LOGDIR / "amaneproxy.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if sys.stdout is not None and SVC.verbose:
        try:
            print(line, flush=True)
        except Exception:
            pass


def read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(default))


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def http_json(url: str, method="GET", body=None, headers=None, timeout=15, bearer=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = dict(headers or {})
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    if bearer:
        h["Authorization"] = "Bearer " + bearer
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else None


def port_free(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.35)
        return s.connect_ex(("127.0.0.1", port)) != 0


def socks_get(port: int, host: str, path: str = "/", https: bool = True, timeout: float = 20.0) -> bytes:
    """经本地 socks5 入口取一次 HTTP 响应 (返回正文)。"""
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.settimeout(timeout)
        s.sendall(b"\x05\x01\x00")
        if s.recv(2) != b"\x05\x00":
            raise RuntimeError("socks5 greeting failed")
        hb = host.encode()
        tport = 443 if https else 80
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + struct.pack(">H", tport))
        rep = s.recv(4)
        if len(rep) < 2 or rep[1] != 0:
            raise RuntimeError("socks5 connect refused (rep=%r)" % rep)
        atyp = rep[3] if len(rep) > 3 else 1
        if atyp == 1:
            s.recv(4)
        elif atyp == 3:
            s.recv(s.recv(1)[0])
        elif atyp == 4:
            s.recv(16)
        s.recv(2)
        if https:
            sock = ssl.create_default_context().wrap_socket(s, server_hostname=host)
        else:
            sock = s
        req = "GET %s HTTP/1.1\r\nHost: %s\r\nAccept: */*\r\nConnection: close\r\nUser-Agent: curl/8\r\n\r\n" % (path, host)
        sock.sendall(req.encode())
        data = b""
        while True:
            try:
                chunk = sock.recv(4096)
            except Exception:
                break
            if not chunk:
                break
            data += chunk
        return data.split(b"\r\n\r\n", 1)[-1]
    finally:
        try:
            s.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 服务主体


class Service:
    # 环境变量覆盖: 优先级 env > amaneproxy.json > 默认值。Docker 里用 env 传端口/监听地址,
    # 这样同一份镜像能直接跑, 不用先改配置。（env 提供的键不会落盘）
    ENV_MAP = {
        "proxy_port": ("AMANEPROXY_PROXY_PORT", int),
        "panel_port": ("AMANEPROXY_PANEL_PORT", int),
        "clash_port": ("AMANEPROXY_CLASH_PORT", int),
        "listen_host": ("AMANEPROXY_LISTEN_HOST", str),
        "panel_host": ("AMANEPROXY_PANEL_HOST", str),
        "amane_url": ("AMANEPROXY_AMANE_URL", str),
        "amane_token_file": ("AMANEPROXY_AMANE_TOKEN_FILE", str),
        "default_outbound": ("AMANEPROXY_DEFAULT_OUTBOUND", str),
        "tray": ("AMANEPROXY_TRAY", lambda v: str(v).strip().lower() in ("1", "true", "yes", "on")),
    }

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.env_keys: set[str] = set()
        self.settings = read_json(SETTINGS_PATH, DEFAULT_SETTINGS)
        for k, v in DEFAULT_SETTINGS.items():
            self.settings.setdefault(k, v)
        self.apply_env()
        self.servers = read_json(SERVERS_PATH, {"servers": DEFAULT_SERVERS}).get("servers") or DEFAULT_SERVERS
        for s in self.servers:
            s.setdefault("cc", s["id"])
        self.rules = read_json(RULES_PATH, {"rules": []}).get("rules") or []
        if not self.settings.get("clash_secret"):
            self.settings["clash_secret"] = "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(24))
        self.proc: subprocess.Popen | None = None
        self.started_at: float | None = None
        self.probe_state: dict[str, dict] = {}
        self.failover_log: list[str] = []
        self.error: str | None = None
        self.lock = threading.RLock()
        self.sync_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.geo_cache: dict[str, dict] = {}
        self.countries = [s["cc"] for s in self.servers]

    # ---------------- 持久化 ----------------

    def apply_env(self) -> None:
        for key, (env, cast) in self.ENV_MAP.items():
            raw = os.environ.get(env)
            if raw is None or raw == "":
                continue
            try:
                self.settings[key] = cast(raw)
                self.env_keys.add(key)
            except Exception:
                log("环境变量 %s=%r 无效, 已忽略" % (env, raw))

    def save_settings(self):
        disk = dict(self.settings)
        for k in self.env_keys:
            disk.pop(k, None)        # 环境变量管的键不写回文件, 保持 amaneproxy.json 干净
        write_json(SETTINGS_PATH, disk)

    def save_servers(self):
        write_json(SERVERS_PATH, {"servers": self.servers})

    def save_rules(self):
        write_json(RULES_PATH, {"rules": self.rules})

    def bootstrap_files(self):
        """把默认文件写到磁盘 (首次运行)。"""
        ROOT.mkdir(parents=True, exist_ok=True)   # 数据目录 (Docker 里是挂进来的卷)
        LOGDIR.mkdir(parents=True, exist_ok=True)
        if not SETTINGS_PATH.exists():
            self.save_settings()
        if not SERVERS_PATH.exists():
            self.save_servers()
        if not RULES_PATH.exists():
            self.rules = self.build_preset_rules(["jav", "west"])
            self.save_rules()

    def build_preset_rules(self, keys: list[str]) -> list[dict]:
        out = []
        for key in keys:
            preset = PRESET_RULES.get(key)
            if not preset:
                continue
            for suffix in preset["suffixes"]:
                out.append({"type": "domain_suffix", "value": suffix,
                            "outbound": preset["outbound"], "src": "preset:%s" % key})
        return out

    # ---------------- sing-box 配置 ----------------

    def probe_port(self, sid: str) -> int:
        base = int(self.settings["proxy_port"]) + 100
        idx = [s["id"] for s in self.servers].index(sid)
        return base + idx + 1

    def build_config(self) -> dict:
        outbounds: list[dict] = []
        for s in self.servers:
            if s["kind"] == "hysteria2":
                hy2 = {
                    "type": "hysteria2",
                    "tag": s["id"],
                    "server": s["server"],
                    "server_port": int(s["port"]),
                    "password": s.get("password", ""),
                    "tls": {
                        "enabled": True,
                        "server_name": s.get("sni") or s["server"],
                        "insecure": bool(s.get("insecure")),
                    },
                }
                # 声明带宽 -> 客户端启用 Brutal 拥塞控制 (服务端 ignore_client_bandwidth=false 时才生效)
                if s.get("up_mbps"):
                    hy2["up_mbps"] = int(s["up_mbps"])
                if s.get("down_mbps"):
                    hy2["down_mbps"] = int(s["down_mbps"])
                outbounds.append(hy2)
            elif s["kind"] == "shadowsocks":
                outbounds.append({
                    "type": "shadowsocks", "tag": s["id"], "server": s["server"],
                    "server_port": int(s["port"]), "method": s.get("method", "none"),
                    "password": s.get("password", ""),
                })
            elif s["kind"] == "socks":
                outbounds.append({
                    "type": "socks", "tag": s["id"], "server": s["server"],
                    "server_port": int(s["port"]), "version": s.get("version", "5"),
                })
            else:
                raise ValueError("未知的服务器类型: %s" % s["kind"])

        # 每个国家一个 selector: 该国全部出口(按 servers.json 顺序, 第一个为默认) + 其他出口 + 直连。
        # 同一个 cc 有多台(例如日本既有新 hysteria2 又有老 SSR)时只生成一个 selector,
        # 否则 tag 撞车 sing-box 直接起不来。首个为默认 -> 想换主出口只要调 servers.json 顺序。
        all_ids = [s["id"] for s in self.servers]
        grouped: list[tuple[str, list[str]]] = []
        for s in self.servers:
            hit = next((g for g in grouped if g[0] == s["cc"]), None)
            if hit:
                hit[1].append(s["id"])
            else:
                grouped.append((s["cc"], [s["id"]]))
        for cc, own in grouped:
            members = own + [x for x in all_ids if x not in own] + ["direct"]
            outbounds.append({"type": "selector", "tag": "sel-" + cc, "outbounds": members, "default": own[0]})
        if len(self.servers) > 1:
            outbounds.append({
                "type": "urltest", "tag": "sel-auto",
                "outbounds": [s["id"] for s in self.servers],
                "url": "http://cp.cloudflare.com/", "interval": "3m", "tolerance": 150,
            })
        outbounds.append({"type": "direct", "tag": "direct"})

        inbounds = [{
            "type": "mixed", "tag": "entry", "listen": self.settings.get("listen_host") or "127.0.0.1",
            "listen_port": int(self.settings["proxy_port"]),
        }]
        probe_rules = []
        for s in self.servers:
            tagname = "probe-" + s["id"]
            inbounds.append({
                "type": "mixed", "tag": tagname, "listen": "127.0.0.1",
                "listen_port": self.probe_port(s["id"]),
            })
            probe_rules.append({"inbound": [tagname], "outbound": s["id"]})

        rule_list: list[dict] = [{"action": "sniff"}]
        rule_list.extend(probe_rules)
        rule_list.append({"ip_is_private": True, "outbound": "direct"})
        rule_list.append({"domain": ["localhost", "localhost.localdomain"], "outbound": "direct"})

        grouped: dict[str, dict] = {}
        tuned = self.settings.get("tuned_outbound") or {}
        for r in self.rules:
            root = str(r.get("value", "")).lstrip(".")
            target = r.get("outbound") or self.settings["default_outbound"]
            if r.get("type", "domain_suffix") == "domain_suffix" and root in tuned:
                target = tuned[root]          # 实测调优后的出口覆盖规则里写的
            mode = r.get("type", "domain_suffix")
            key = "%s|%s" % (target, mode)
            grouped.setdefault(key, {"target": target, "mode": mode, "values": []})
            grouped[key]["values"].append(r["value"])
        for key, grp in grouped.items():
            field = {"domain": "domain", "domain_suffix": "domain_suffix",
                     "domain_keyword": "domain_keyword", "domain_regex": "domain_regex"}.get(grp["mode"], "domain_suffix")
            rule_list.append({field: sorted(set(grp["values"])), "outbound": self.resolve_outbound(grp["target"])})

        cfg = {
            "log": {
                "level": self.settings.get("log_level", "info"),
                "output": str(LOGDIR / "sing-box.log"),
                "timestamp": True,
            },
            "dns": {"servers": [{"type": "local", "tag": "local"}], "final": "local"},
            "inbounds": inbounds,
            "outbounds": outbounds,
            "route": {"rules": rule_list, "final": self.resolve_outbound(self.settings["default_outbound"])},
            "experimental": {
                "clash_api": {
                    "external_controller": "127.0.0.1:%d" % int(self.settings["clash_port"]),
                    "secret": self.settings["clash_secret"],
                    "default_mode": "rule",
                }
            },
        }
        return cfg

    def resolve_outbound(self, target: str | None) -> str:
        if not target or target == "direct":
            return "direct"
        if target == "auto":
            return "sel-auto" if len(self.servers) > 1 else "direct"
        ids = [s["id"] for s in self.servers]
        ccs = [s["cc"] for s in self.servers]
        if target in ids:
            return "sel-" + next(s["cc"] for s in self.servers if s["id"] == target)
        if target in ccs:
            return "sel-" + target
        return "direct"

    def write_config(self) -> dict:
        cfg = self.build_config()
        write_json(CONFIG_PATH, cfg)
        return cfg

    # ---------------- 进程管理 ----------------

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start_singbox(self, retries: int = 4) -> None:
        with self.lock:
            if self.running():
                return
            if not BIN.exists():
                raise RuntimeError("缺少内核: %s" % BIN)
            self.write_config()
            LOGDIR.mkdir(parents=True, exist_ok=True)
            try:
                p = LOGDIR / "sing-box.log"
                if p.exists() and p.stat().st_size > 8 * 1024 * 1024:
                    p.unlink()
            except Exception:
                pass
            last_err = ""
            for attempt in range(max(1, retries)):
                # 端口被上一轮还没退干净的进程占着时先等一下, 否则 bind 失败
                if not port_free(int(self.settings["proxy_port"])):
                    time.sleep(1.2)
                    continue
                self.proc = subprocess.Popen(
                    [str(BIN), "run", "-c", str(CONFIG_PATH), "-D", str(ROOT)],
                    cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                )
                SB_PID_PATH.write_text(str(self.proc.pid), encoding="utf-8")
                self.started_at = time.time()
                time.sleep(1.6)
                if self.proc.poll() is None:
                    self.error = None
                    log("sing-box 已启动 pid=%s 入口=127.0.0.1:%s" % (self.proc.pid, self.settings["proxy_port"]))
                    return
                try:
                    last_err = (LOGDIR / "sing-box.log").read_text(encoding="utf-8", errors="replace")[-1200:]
                except Exception:
                    last_err = ""
                time.sleep(1.0)
            self.error = "sing-box 启动失败 (已重试 %d 次):\n%s" % (retries, last_err)
            raise RuntimeError(self.error)

    def stop_singbox(self) -> None:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=6)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
                log("sing-box 已停止")
            self.proc = None
            self.started_at = None
            try:
                SB_PID_PATH.unlink()
            except Exception:
                pass

    def restart(self) -> None:
        self.stop_singbox()
        self.start_singbox()
        self.probe_all()

    # ---------------- 探测 / 出口 IP ----------------

    def geo_of(self, ip: str) -> dict:
        if ip in self.geo_cache:
            return self.geo_cache[ip]
        try:
            data = http_json("http://ip-api.com/json/%s?fields=status,country,countryCode,city,isp" % ip, timeout=12)
        except Exception as e:
            data = {"country": "?", "countryCode": "?", "city": "", "isp": str(e)[:40]}
        self.geo_cache[ip] = data
        return data

    def probe_one(self, s: dict) -> dict:
        port = self.probe_port(s["id"])
        out = {"id": s["id"], "cc": s["cc"], "ts": time.time(), "ok": False, "ip": None, "ms": None, "error": None}
        t0 = time.time()
        try:
            body = socks_get(port, "ip-api.com", "/json/?fields=status,country,countryCode,city,isp,query", https=False, timeout=20)
            data = json.loads(body.decode("utf-8", "replace"))
            if data.get("status") == "success":
                out.update({"ok": True, "ip": data.get("query"),
                            "country": data.get("country"), "code": data.get("countryCode"),
                            "city": data.get("city"), "isp": data.get("isp")})
            else:
                raise RuntimeError(str(data)[:80])
        except Exception as e1:
            try:
                body = socks_get(port, "api.ipify.org", "/", https=True, timeout=20)
                ip = body.decode("utf-8", "replace").strip()
                if not ip or not ip[0].isdigit():
                    raise RuntimeError("非 IP 响应")
                g = self.geo_of(ip)
                out.update({"ok": True, "ip": ip, "country": g.get("country"),
                            "code": g.get("countryCode"), "city": g.get("city"), "isp": g.get("isp")})
            except Exception as e2:
                out["error"] = "%s / %s" % (str(e1)[:60], str(e2)[:60])
        out["ms"] = int((time.time() - t0) * 1000)
        with self.lock:
            self.probe_state[s["id"]] = out
        return out

    def probe_all(self) -> list[dict]:
        if not self.running():
            return []
        results = []
        for s in self.servers:
            try:
                results.append(self.probe_one(s))
            except Exception as e:
                results.append({"id": s["id"], "ok": False, "error": str(e)[:80], "ts": time.time()})
        return results

    # ---------------- clash API (热切换 selector) ----------------

    def clash(self, path: str, method="GET", body=None):
        url = "http://127.0.0.1:%d%s" % (int(self.settings["clash_port"]), path)
        return http_json(url, method=method, body=body, bearer=self.settings["clash_secret"], timeout=10)

    def selector_current(self, tag: str) -> str | None:
        try:
            data = self.clash("/proxies/" + urllib.parse.quote(tag))
            return data.get("now")
        except Exception:
            return None

    def selector_switch(self, tag: str, member: str) -> bool:
        try:
            self.clash("/proxies/" + urllib.parse.quote(tag), method="PUT", body={"name": member})
            log("切换 %s -> %s" % (tag, member))
            return True
        except Exception as e:
            log("切换失败 %s -> %s: %s" % (tag, member, e))
            return False

    def healthy_ids(self) -> list[str]:
        return [s["id"] for s in self.servers if self.probe_state.get(s["id"], {}).get("ok")]

    def failover_tick(self) -> None:
        """主出口不健康时切到健康备选, 恢复后切回。"""
        if not self.running() or not self.settings.get("auto_failover"):
            return
        healthy = self.healthy_ids()
        # 按 cc 分组: 优先切回该国的首选出口(servers.json 里排第一的健康者),
        # 本国全挂才退到其它国家的出口。
        grouped: dict[str, list[str]] = {}
        for s in self.servers:
            grouped.setdefault(s["cc"], []).append(s["id"])
        for cc, own in grouped.items():
            tag = "sel-" + cc
            want = next((sid for sid in own if sid in healthy), None)
            if want is None:
                want = next((sid for sid in healthy), None)
            if want is None:
                continue  # 全挂: 保持现状
            if self.selector_current(tag) != want:
                if self.selector_switch(tag, want):
                    msg = "%s[%s] %s" % (time.strftime("%H:%M:%S"), COUNTRY_NAMES.get(cc, cc),
                                         ("恢复 -> %s" % want) if want == own[0] else ("故障转移 -> %s" % want))
                    self.failover_log.insert(0, msg)
                    self.failover_log = self.failover_log[:50]
                    log(msg)

    # ---------------- Amane 集成 ----------------

    def amane_token(self) -> str | None:
        env = os.environ.get("AMANEPROXY_AMANE_TOKEN")
        if env and env.strip():
            return env.strip()
        cands: list[Path] = []
        if self.settings.get("amane_token_file"):
            cands.append(Path(str(self.settings["amane_token_file"])))
        cands += [
            ROOT / "amane-token",                                          # Docker: 挂进数据目录
            Path(os.environ.get("LOCALAPPDATA") or "_") / "Amane" / "token",   # Windows
            Path(os.environ.get("APPDATA") or "_") / "Amane" / "token",
            Path.home() / ".local" / "share" / "Amane" / "token",           # Linux
        ]
        for p in cands:
            try:
                if p.is_file():
                    tok = p.read_text(encoding="utf-8").strip()
                    if tok:
                        return tok
            except Exception:
                continue
        return None

    def amane_url(self) -> str:
        base = os.environ.get("AMANEPROXY_AMANE_URL") or self.settings.get("amane_url") or "http://127.0.0.1:18100"
        return str(base).rstrip("/")

    def amane_get_config(self) -> dict:
        token = self.amane_token()
        if not token:
            raise RuntimeError("找不到 Amane token 文件")
        return http_json(self.amane_url() + "/api/config", bearer=token, timeout=20)

    def amane_set_proxy(self, value: str | None, remember: bool = True) -> dict:
        token = self.amane_token()
        hot = self.amane_get_config()
        network = dict(hot.get("network") or {})
        if remember and not self.settings.get("amaneproxy_enabled"):
            self.settings["amaneproxy_previous"] = network.get("proxy")
        network["proxy"] = value
        http_json(self.amane_url() + "/api/config", method="PATCH", body={"network": network}, bearer=token, timeout=40)
        self.settings["amaneproxy_enabled"] = bool(value and "127.0.0.1:%d" % int(self.settings["proxy_port"]) in value)
        self.save_settings()
        log("Amane network.proxy = %r" % value)
        return {"proxy": value, "previous": self.settings.get("amaneproxy_previous")}

    def amane_enable(self) -> dict:
        # 用 http:// 而不是 socks5://: 走 SOCKS5 时 httpx 会在本地先把域名解析成 IP 再交给代理,
        # 按域名分流就失效了 (而且 DNS 被污染时拿到的 IP 也没用)。HTTP CONNECT 会把域名原样带过来。
        return self.amane_set_proxy("http://127.0.0.1:%d" % int(self.settings["proxy_port"]))

    def amane_disable(self) -> dict:
        prev = self.settings.get("amaneproxy_previous")
        res = self.amane_set_proxy(prev, remember=False)
        self.settings["amaneproxy_enabled"] = False
        self.settings["amaneproxy_previous"] = None
        self.save_settings()
        return res

    # ---------------- 分流自检 ----------------

    def selftest(self) -> dict:
        """对若干域名各发一次连接, 读 sing-box 日志确认流量走了哪个出口。"""
        if not self.running():
            raise RuntimeError("sing-box 未运行")
        logfile = LOGDIR / "sing-box.log"
        start_size = logfile.stat().st_size if logfile.exists() else 0

        cases = []
        seen = set()
        for r in self.rules:
            if r.get("type") not in ("domain_suffix", "domain"):
                continue
            host = str(r["value"]).lstrip(".")
            if host in seen:
                continue
            seen.add(host)
            cases.append({"host": host, "expect": r.get("outbound")})
            if len(cases) >= 10:
                break

        results = []
        for c in cases:
            host = c["host"]
            try:
                s = socket.create_connection(("127.0.0.1", int(self.settings["proxy_port"])), timeout=8)
                s.settimeout(8)
                s.sendall(b"\x05\x01\x00")
                s.recv(2)
                hb = host.encode()
                s.sendall(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + struct.pack(">H", 443))
                rep = s.recv(4)
                s.close()
                ok = len(rep) >= 2 and rep[1] == 0
            except Exception:
                ok = False
            results.append({"host": host, "expect": c["expect"], "connected": ok})

        time.sleep(1.2)
        tag_of: dict[str, str] = {}
        try:
            text = logfile.read_text(encoding="utf-8", errors="replace")[start_size:]
            for line in text.splitlines():
                m = re.search(r"outbound/([A-Za-z0-9_\-]+)(?:\[([^\]]+)\])?.*?connection to ([^\s:]+)", line)
                if m:
                    tag_of.setdefault(m.group(3), m.group(2) or m.group(1))
                m2 = re.search(r"via outbound/([A-Za-z0-9_\-]+).*?connection to ([^\s:]+)", line)
                if m2:
                    tag_of.setdefault(m2.group(2), m2.group(1))
        except Exception as e:
            log("自检读日志失败: %s" % e)

        for r in results:
            r["actual"] = tag_of.get(r["host"], "?")
            r["match"] = (r["actual"] == self.resolve_outbound(r["expect"])) if r["expect"] else None
        return {"cases": results, "raw": tag_of}

    # ---------------- 域名同步: 自动获取站点最新域名并补规则 ----------------

    def source_outbound(self, source: str | None) -> str:
        m = self.settings.get("source_outbound") or {}
        if source and source in m:
            val = m[source]
            return val if val and val != "default" else self.settings["default_outbound"]
        return self.settings["default_outbound"]

    def rule_outbound_of(self, root: str) -> str:
        for r in self.rules:
            if str(r.get("value")).lstrip(".") == root:
                return r.get("outbound") or self.settings["default_outbound"]
        return self.settings["default_outbound"]

    def _check_domains(self, targets: list[str], force: bool = False) -> dict[str, dict]:
        """并行探测域名可达性 + 跟随跳转; 最近测通的域名按时效跳过。"""
        port = int(self.settings["proxy_port"])
        timeout = float(self.settings.get("sync_domain_timeout", 6))
        max_hops = int(self.settings.get("sync_max_hops", 3))
        workers = max(1, int(self.settings.get("sync_workers", 16)))
        ttl = float(self.settings.get("sync_recheck_minutes", 30)) * 60
        deadline = time.time() + float(self.settings.get("sync_deadline_seconds", 120))
        prev = self.settings.get("domain_status") or {}
        status: dict[str, dict] = {}
        todo: list[str] = []
        for root in targets:
            old = prev.get(root) or {}
            if not force and old.get("ok") and (time.time() - float(old.get("ts") or 0)) < ttl:
                status[root] = old
            else:
                todo.append(root)

        def check(root: str):
            if time.time() > deadline:
                return root, {"ok": False, "status": 0, "err": "本次超时预算用尽, 下次再测", "ts": time.time()}
            try:
                final, st, hops = follow_redirects(port, "http://%s/" % root, max_hops=max_hops, timeout=timeout)
                return root, {"ok": bool(st), "status": st, "final": final,
                              "final_root": root_domain(urllib.parse.urlsplit(final).hostname),
                              "hops": [h[1] for h in hops], "ts": time.time()}
            except Exception as e:
                return root, {"ok": False, "status": 0, "err": str(e)[:90], "ts": time.time()}

        if todo:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for root, info in ex.map(check, todo):
                    status[root] = info
        return status

    def sync_domains(self, manual: bool = False, force: bool = False) -> dict:
        """三路取域名: Amane 的源配置 / Amane 网络检测 / 跟随站点跳转 (+候选域名), 并补规则。"""
        if not self.running():
            raise RuntimeError("sing-box 未运行")
        port = int(self.settings["proxy_port"])
        max_domains = int(self.settings.get("sync_max_domains", 80))
        added: list[dict] = []
        redirects: list[dict] = []
        cand_hits: list[dict] = []
        errors: list[str] = []
        amane_status: dict[str, str] = {}
        rules_before = len(self.rules)

        def has_rule(root: str) -> bool:
            return any(str(r.get("value")).lstrip(".") == root for r in self.rules)

        def add_rule(root: str, outbound: str, src: str, note: str = "") -> bool:
            if not root or has_rule(root):
                return False
            self.rules.append({"type": "domain_suffix", "value": root, "outbound": outbound, "src": src})
            added.append({"domain": root, "outbound": outbound, "src": src, "note": note})
            return True

        # ---- 1) Amane 侧: site_config.base_url + 网络检测的真实 URL ----
        if self.settings.get("sync_from_amane"):
            try:
                hot = self.amane_get_config()
                site_cfg = ((hot.get("scraping") or {}).get("site_config") or {})
                for site, cfg in site_cfg.items():
                    base = (cfg or {}).get("base_url")
                    if base:
                        root = root_domain(urllib.parse.urlsplit(base).hostname or base)
                        if root:
                            add_rule(root, self.source_outbound(site), "auto:amane:%s" % site, "Amane base_url")
            except Exception as e:
                errors.append("读 Amane 配置失败: %s" % str(e)[:80])
            try:
                rep = http_json(self.amane_url() + "/api/network/check", method="POST", body={},
                                bearer=self.amane_token(), timeout=300)
                for it in rep.get("items") or []:
                    sid = it.get("source_id") or ""
                    if sid:
                        amane_status[sid] = it.get("status") or "?"
                    url = it.get("url")
                    if not url:
                        continue
                    root = root_domain(urllib.parse.urlsplit(url).hostname)
                    if root:
                        add_rule(root, self.source_outbound(sid), "auto:amane:%s" % sid, "Amane 网络检测")
            except Exception as e:
                errors.append("Amane 网络检测失败: %s" % str(e)[:80])

        # ---- 2) 跟随跳转 / 存活状态 (并行) ----
        targets = sorted({str(r.get("value")).lstrip(".") for r in self.rules
                          if r.get("type") == "domain_suffix" and r.get("value")})[:max_domains]
        status: dict[str, dict] = {}
        if targets and (self.settings.get("sync_follow_redirect") or self.settings.get("sync_try_candidates")):
            status = self._check_domains(targets, force=force)

            if self.settings.get("sync_follow_redirect"):
                for root, info in list(status.items()):
                    final_root = info.get("final_root")
                    if final_root and final_root != root:
                        if add_rule(final_root, self.rule_outbound_of(root), "auto:redirect:%s" % root,
                                    "跳转 %s" % root):
                            redirects.append({"from": root, "to": final_root})

            if self.settings.get("sync_try_candidates"):
                cand_map = self.settings.get("candidates") or {}
                for root, info in status.items():
                    if info.get("ok"):
                        continue
                    for cand in (cand_map.get(root) or [])[:5]:
                        croot = root_domain(cand)
                        if not croot or has_rule(croot):
                            continue
                        try:
                            st, _hd, _b = proxy_fetch(port, "https://%s/" % cand, timeout=8)
                        except Exception:
                            continue
                        if st:
                            if add_rule(croot, self.rule_outbound_of(root), "auto:candidate:%s" % root,
                                        "候选域名 (%s 不通)" % root):
                                cand_hits.append({"from": root, "to": croot, "status": st})
                            break

        dead = [{"domain": k, "status": v.get("status"), "err": v.get("err")}
                for k, v in status.items() if not v.get("ok")]

        # ---- 3) 出口实测调优 (当前出口不通时) ----
        try:
            tune_notes = self.tune_outbounds(status, force=force)
        except Exception as e:
            tune_notes = []
            errors.append("出口调优失败: %s" % str(e)[:100])

        self.settings["domain_status"] = status
        self.settings["sync_last"] = time.time()
        stamp = time.strftime("%m-%d %H:%M")
        lines = []
        for a in added:
            lines.append("%s  + 规则 %s -> %s [%s]" % (stamp, a["domain"], a["outbound"], a["src"]))
        for n in tune_notes:
            lines.append("%s  调优 %s: %s -> %s  [%s]" % (stamp, n["domain"], n["from"], n["to"], n["why"]))
        if dead and len(dead) <= 20:
            lines.append("%s  未响应: %s" % (stamp, ", ".join(d["domain"] for d in dead)))
        elif dead:
            lines.append("%s  未响应: %s 等 %d 个" % (stamp, ", ".join(d["domain"] for d in dead[:10]), len(dead)))
        for e in errors:
            lines.append("%s  %s" % (stamp, e))
        if not lines:
            lines.append("%s  无变化 (检查了 %d 个域名)" % (stamp, len(targets)))
        self.settings["sync_log"] = (lines + (self.settings.get("sync_log") or []))[:120]
        self.save_settings()          # 先落盘, 后面重载内核失败也不丢记录

        if len(self.rules) != rules_before:
            self.save_rules()
            try:
                self.stop_singbox()
                self.start_singbox()
                log("域名同步新增 %d 条规则, 已重载内核" % (len(self.rules) - rules_before))
            except Exception as e:
                errors.append("重载内核失败: %s" % str(e)[:160])
                log("域名同步: 重载内核失败 %s" % e)

        report = {"added": added, "redirects": redirects, "candidates": cand_hits, "dead": dead,
                  "checked": len(targets), "amane_status": amane_status, "errors": errors,
                  "tuned": tune_notes, "rules_total": len(self.rules), "ts": self.settings["sync_last"]}
        self.last_sync_report = report
        log("域名同步完成: +%d 规则, 跳转 +%d, 候选 +%d, 不通 %d" % (len(added), len(redirects), len(cand_hits), len(dead)))
        return report

    def sync_async(self, force: bool = False) -> dict:
        """后台跑一次同步: HTTP 请求立即返回, 面板靠轮询看进度。"""
        if not self.sync_lock.acquire(blocking=False):
            return {"running": True, "skipped": True}

        def run():
            try:
                self.last_sync_report = self.sync_domains(force=force)
            except Exception as e:
                self.last_sync_report = {"error": str(e)[:300], "ts": time.time()}
                log("域名同步失败: %s" % e)
            finally:
                self.sync_lock.release()

        threading.Thread(target=run, daemon=True).start()
        return {"running": True}

    def sync_loop(self) -> None:
        self.stop_flag.wait(25)
        while not self.stop_flag.is_set():
            try:
                if self.settings.get("sync_enabled") and self.running():
                    self.sync_async()
            except Exception as e:
                log("域名同步异常: %s" % e)
            try:
                hours = max(0.25, float(self.settings.get("sync_interval_hours", 6)))
            except Exception:
                hours = 6.0
            self.stop_flag.wait(int(hours * 3600))

    @staticmethod
    def _ok_code(code) -> bool:
        return isinstance(code, int) and 200 <= code < 400

    def _cc_of_outbound(self, target: str | None) -> str | None:
        if not target:
            return None
        if target in [s["id"] for s in self.servers]:
            return next(s["cc"] for s in self.servers if s["id"] == target)
        if target in [s["cc"] for s in self.servers]:
            return target
        if target == "default":
            return self._cc_of_outbound(self.settings.get("default_outbound"))
        return None

    def tune_outbounds(self, status: dict, force: bool = False) -> list[dict]:
        """实测各出口在某个域名上的表现, 并且**只在原出口拿不到 2xx/3xx 时**才改走能通的那个。

        不按“谁快用谁”自动优化: 地域站点(如 dmm 只认日本 IP)不能因为美国/韩国更快就换走;
        速度快慢留给面板上的手动切换。force 只是把全部域名都拿来实测(不改变“只在原出口不通时才改”的判定)。
        """
        tuned = dict(self.settings.get("tuned_outbound") or {})
        notes: list[dict] = []
        if not self.settings.get("sync_tune_outbound") or not status:
            return notes
        servers = {s["id"]: s["cc"] for s in self.servers}
        healthy = [sid for sid in servers if (self.probe_state.get(sid) or {}).get("ok")]
        mode = self.settings.get("sync_tune_mode", "fallback")
        if force or mode == "fastest":
            need = list(status.keys())
        else:
            need = [root for root, info in status.items() if not self._ok_code(info.get("status"))]
        need = need[: int(self.settings.get("sync_tune_max", 30))]
        if not need or len(healthy) < 2:
            return notes
        pairs = [(root, sid) for root in need for sid in healthy]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(2, int(self.settings.get("sync_workers", 16)))) as ex:
            results = list(ex.map(lambda pr: probe_via_socks(self.probe_port(pr[1]), pr[0]), pairs))
        for (root, sid), (code, ms) in zip(pairs, results):
            status.setdefault(root, {}).setdefault("by_outbound", {})[sid] = {"status": code, "ms": ms}

        sid_of_cc = {cc: sid for sid, cc in servers.items()}
        never = {str(x).strip().lower() for x in (self.settings.get("tune_never") or [])}
        something_changed = False
        for root in need:
            if root in never:
                continue
            bo = status[root].get("by_outbound") or {}
            eff_cc = tuned.get(root) or self._cc_of_outbound(self.rule_outbound_of(root))
            cur_sid = sid_of_cc.get(eff_cc) if eff_cc else None
            cur_code = (bo.get(cur_sid) or {}).get("status")
            if mode != "fastest" and cur_sid and self._ok_code(cur_code):
                # 原出口本来就通 -> 不动 (之前调优过的现在恢复了则撑销调优)
                if root in tuned:
                    tuned.pop(root)
                    something_changed = True
                continue
            good = {sid: v for sid, v in bo.items() if self._ok_code(v["status"])}
            if not good:
                continue                      # 所有出口都不行: 保持原判
            best_sid = min(good.items(), key=lambda kv: kv[1]["ms"])[0]
            best_cc = servers[best_sid]
            why = "  ".join("%s:%s/%dms" % (servers[k], v["status"], v["ms"]) for k, v in sorted(bo.items()))
            if eff_cc != best_cc:
                tuned[root] = best_cc
                something_changed = True
                notes.append({"domain": root, "from": eff_cc or "默认", "to": best_cc, "why": why})
        if something_changed or True:
            self.settings["tuned_outbound"] = tuned
        return notes

    # ---------------- 状态快照 ----------------

    def snapshot(self) -> dict:
        with self.lock:
            selectors = {}
            for s in self.servers:
                tag = "sel-" + s["cc"]
                selectors[tag] = self.selector_current(tag)
            sync = {
                "enabled": self.settings.get("sync_enabled"),
                "interval_hours": self.settings.get("sync_interval_hours"),
                "from_amane": self.settings.get("sync_from_amane"),
                "follow_redirect": self.settings.get("sync_follow_redirect"),
                "try_candidates": self.settings.get("sync_try_candidates"),
                "last": self.settings.get("sync_last"),
                "log": self.settings.get("sync_log") or [],
                "domain_status": self.settings.get("domain_status") or {},
                "source_outbound": self.settings.get("source_outbound") or {},
                "candidates": self.settings.get("candidates") or {},
                "tuned": self.settings.get("tuned_outbound") or {},
                "tune_mode": self.settings.get("sync_tune_mode", "fallback"),
                "tune_enabled": self.settings.get("sync_tune_outbound"),
                "tune_never": self.settings.get("tune_never") or [],
                "auto_rules": sum(1 for r in self.rules if str(r.get("src") or "").startswith("auto:")),
                "running": self.sync_lock.locked(),
                "report": getattr(self, "last_sync_report", None),
            }
            amane = {"reachable": False, "proxy": None, "token": bool(self.amane_token()), "error": None}
            try:
                hot = self.amane_get_config()
                amane.update({"reachable": True, "proxy": (hot.get("network") or {}).get("proxy")})
            except Exception as e:
                amane["error"] = str(e)[:120]
            sb_version = None
            try:
                if BIN.exists():
                    sb_version = subprocess.run([str(BIN), "version"], capture_output=True, text=True,
                                                timeout=15, creationflags=CREATE_NO_WINDOW).stdout.splitlines()[0]
            except Exception:
                pass
            return {
                "version": VERSION,
                "singbox_version": sb_version,
                "running": self.running(),
                "uptime": int(time.time() - self.started_at) if self.started_at else 0,
                "error": self.error,
                "settings": self.settings,
                "servers": [{**{k: v for k, v in s.items() if k != "password"}, "has_password": bool(s.get("password"))}
                            for s in self.servers],
                "probe": self.probe_state,
                "selectors": selectors,
                "rules": self.rules,
                "presets": {k: {"label": v["label"], "outbound": v["outbound"], "count": len(v["suffixes"])}
                            for k, v in PRESET_RULES.items()},
                "failover_log": self.failover_log,
                "amane": amane,
                "sync": sync,
                "sync_report": getattr(self, "last_sync_report", None),
                "ports": {"entry": self.settings["proxy_port"], "panel": self.settings["panel_port"],
                          "clash": self.settings["clash_port"]},
                "probe_ports": {s["id"]: self.probe_port(s["id"]) for s in self.servers},
            }

    # ---------------- 后台线程 ----------------

    def health_loop(self) -> None:
        while not self.stop_flag.is_set():
            try:
                if not self.running():
                    self.start_singbox()
                self.probe_all()
                self.failover_tick()
            except Exception as e:
                self.error = str(e)
                log("健康检查异常: %s" % e)
            self.stop_flag.wait(max(15, int(self.settings.get("health_interval", 60))))

    def watchdog_loop(self) -> None:
        while not self.stop_flag.is_set():
            self.stop_flag.wait(10)
            if self.stop_flag.is_set():
                break
            try:
                if self.proc is not None and self.proc.poll() is not None:
                    log("sing-box 意外退出 (code=%s), 重启" % self.proc.returncode)
                    tray_notify("AmaneProxy", "sing-box 意外退出 (code=%s)，已自动拉起" % self.proc.returncode, 8000)
                    self.stop_singbox()
                    self.start_singbox()
            except Exception as e:
                log("看门狗异常: %s" % e)

    def shutdown(self, *_a) -> None:
        self.stop_flag.set()
        self.stop_singbox()
        try:
            if PID_PATH.exists() and PID_PATH.read_text().strip() == str(os.getpid()):
                PID_PATH.unlink()
        except Exception:
            pass
        log("管理器退出")


SVC = Service()


# ---------------------------------------------------------------- 面板 HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "AmaneProxy/" + VERSION

    def log_message(self, fmt, *args):  # 静音
        pass

    def _send(self, code: int, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                html = PANEL_HTML.read_text(encoding="utf-8")
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/api/state":
                return self._json(SVC.snapshot())
            if path == "/api/log":
                tail = 200
                try:
                    tail = int(self.path.split("tail=")[1].split("&")[0])
                except Exception:
                    pass
                out = {}
                for name in ("sing-box.log", "amaneproxy.log"):
                    p = LOGDIR / name
                    out[name] = p.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:] if p.exists() else []
                return self._json(out)
            if path == "/api/selftest":
                return self._json(SVC.selftest())
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": str(e), "trace": traceback.format_exc()[-800:]}, 500)

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            body = {}
        try:
            if path == "/api/control":
                action = body.get("action")
                if action == "start":
                    SVC.start_singbox()
                elif action == "stop":
                    SVC.stop_singbox()
                elif action == "restart":
                    SVC.restart()
                elif action == "reload":
                    SVC.stop_singbox()
                    SVC.start_singbox()
                    SVC.probe_all()
                elif action == "probe":
                    SVC.probe_all()
                elif action == "failover":
                    SVC.failover_tick()
                else:
                    return self._json({"error": "未知动作"}, 400)
                return self._json({"ok": True, "state": SVC.snapshot()})

            if path == "/api/sync":
                action = body.get("action")
                if action == "run":
                    res = SVC.sync_async(force=bool(body.get("force")))
                    return self._json({"ok": True, "sync": res, "state": SVC.snapshot()})
                if action == "status":
                    return self._json({"ok": True, "sync": SVC.snapshot()["sync"]})
                if action == "clear_log":
                    SVC.settings["sync_log"] = []
                    SVC.save_settings()
                    return self._json({"ok": True, "state": SVC.snapshot()})
                if action == "clear_tuned":
                    SVC.settings["tuned_outbound"] = {}
                    SVC.save_settings()
                    try:
                        SVC.stop_singbox()
                        SVC.start_singbox()
                    except Exception as e:
                        log("清除调优后重载失败: %s" % e)
                    return self._json({"ok": True, "state": SVC.snapshot()})
                for key, field in (("enabled", "sync_enabled"), ("from_amane", "sync_from_amane"),
                                   ("follow_redirect", "sync_follow_redirect"),
                                   ("try_candidates", "sync_try_candidates"),
                                   ("tune_outbound", "sync_tune_outbound")):
                    if key in body:
                        SVC.settings[field] = bool(body[key])
                if "interval_hours" in body:
                    SVC.settings["sync_interval_hours"] = max(0.25, float(body["interval_hours"]))
                if "max_domains" in body:
                    SVC.settings["sync_max_domains"] = max(20, int(body["max_domains"]))
                if "source_outbound" in body:
                    SVC.settings["source_outbound"] = {str(k): str(v) for k, v in (body["source_outbound"] or {}).items()}
                if "candidates" in body:
                    cand = {}
                    for k, v in (body["candidates"] or {}).items():
                        vals = [str(x).strip() for x in (v if isinstance(v, list) else str(v).split(",")) if str(x).strip()]
                        if vals:
                            cand[str(k).strip()] = vals
                    SVC.settings["candidates"] = cand
                if "tune_mode" in body and body["tune_mode"] in ("fallback", "fastest"):
                    SVC.settings["sync_tune_mode"] = body["tune_mode"]
                if "tune_never_text" in body:
                    SVC.settings["tune_never"] = [x.strip().lower() for x in
                                                  str(body["tune_never_text"]).replace("，", "\n").replace(",", "\n").splitlines()
                                                  if x.strip()]
                if "source_outbound_text" in body:
                    m = {}
                    for line in str(body["source_outbound_text"]).splitlines():
                        line = line.strip()
                        if not line or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        m[k.strip()] = v.strip()
                    SVC.settings["source_outbound"] = m
                if "candidates_text" in body:
                    cand = {}
                    for line in str(body["candidates_text"]).splitlines():
                        line = line.strip()
                        if not line or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        vals = [x.strip() for x in v.replace("，", ",").split(",") if x.strip()]
                        if vals:
                            cand[k.strip()] = vals
                    SVC.settings["candidates"] = cand
                SVC.save_settings()
                return self._json({"ok": True, "state": SVC.snapshot()})

            if path == "/api/settings":
                for k, v in (body or {}).items():
                    if k in ("probe_url", "default_outbound", "auto_failover", "health_interval",
                             "log_level", "proxy_port", "panel_port", "clash_port", "tray"):
                        SVC.settings[k] = v
                SVC.save_settings()
                if "tray" in body:
                    set_tray(bool(body["tray"]))     # 立即生效, 不用重启管理器
                if any(k in body for k in ("proxy_port", "clash_port", "log_level")):
                    SVC.restart()
                return self._json({"ok": True, "state": SVC.snapshot()})

            if path == "/api/rules":
                action = body.get("action")
                if action == "add":
                    value = (body.get("value") or "").strip().lstrip(".")
                    if value:
                        SVC.rules.append({"type": body.get("type") or "domain_suffix",
                                          "value": value, "outbound": body.get("outbound") or "auto",
                                          "src": "manual"})
                elif action == "del":
                    idx = int(body.get("index", -1))
                    if 0 <= idx < len(SVC.rules):
                        SVC.rules.pop(idx)
                elif action == "insert_preset":
                    key = body.get("preset")
                    preset = PRESET_RULES.get(key)
                    if preset:
                        have = {r["value"] for r in SVC.rules}
                        for suffix in preset["suffixes"]:
                            if suffix not in have:
                                SVC.rules.append({"type": "domain_suffix", "value": suffix,
                                                  "outbound": preset["outbound"], "src": "preset:%s" % key})
                elif action == "remove_preset":
                    key = body.get("preset")
                    preset = PRESET_RULES.get(key)
                    if preset:
                        SVC.rules = [r for r in SVC.rules if r["value"] not in set(preset["suffixes"])]
                elif action == "clear_auto":
                    SVC.rules = [r for r in SVC.rules if not str(r.get("src") or "").startswith("auto:")]
                elif action == "clear":
                    SVC.rules = []
                else:
                    return self._json({"error": "未知动作"}, 400)
                SVC.save_rules()
                SVC.stop_singbox()
                SVC.start_singbox()
                return self._json({"ok": True, "state": SVC.snapshot()})

            if path == "/api/servers":
                sid = body.get("id")
                for s in SVC.servers:
                    if s["id"] == sid:
                        for k in ("label", "cc", "kind", "server", "port", "sni", "insecure", "password", "method", "version", "note", "up_mbps", "down_mbps"):
                            if k in body:
                                s[k] = body[k]
                        for k in ("port", "up_mbps", "down_mbps"):
                            if k in body:
                                s[k] = int(body[k])
                SVC.save_servers()
                SVC.restart()
                return self._json({"ok": True, "state": SVC.snapshot()})

            if path == "/api/server-add":
                sid = (body.get("id") or "").strip().lower()
                if not re.fullmatch(r"[a-z0-9_]{2,16}", sid or ""):
                    return self._json({"error": "id 只能是 2-16 位小写字母/数字/下划线"}, 400)
                if any(s["id"] == sid for s in SVC.servers):
                    return self._json({"error": "id 已存在"}, 400)
                SVC.servers.append({
                    "id": sid, "cc": (body.get("cc") or sid).lower(), "label": body.get("label") or sid,
                    "kind": body.get("kind") or "hysteria2", "server": body.get("server") or "",
                    "port": int(body.get("port") or 0), "sni": body.get("sni") or "", "insecure": bool(body.get("insecure")),
                    "password": body.get("password") or "", "method": body.get("method") or "none",
                    "up_mbps": int(body.get("up_mbps") or 0), "down_mbps": int(body.get("down_mbps") or 0),
                })
                SVC.countries = [s["cc"] for s in SVC.servers]
                SVC.save_servers()
                SVC.restart()
                return self._json({"ok": True, "state": SVC.snapshot()})

            if path == "/api/server-del":
                sid = body.get("id")
                SVC.servers = [s for s in SVC.servers if s["id"] != sid]
                SVC.countries = [s["cc"] for s in SVC.servers]
                SVC.save_servers()
                SVC.restart()
                return self._json({"ok": True, "state": SVC.snapshot()})

            if path == "/api/select":
                tag = body.get("tag")
                member = body.get("member")
                if body.get("auto_failover") is not None:
                    SVC.settings["auto_failover"] = bool(body["auto_failover"])
                    SVC.save_settings()
                if tag and member:
                    SVC.selector_switch(tag, member)
                return self._json({"ok": True, "state": SVC.snapshot()})

            if path == "/api/amane":
                action = body.get("action")
                if action == "enable":
                    res = SVC.amane_enable()
                elif action == "disable":
                    res = SVC.amane_disable()
                elif action == "set":
                    res = SVC.amane_set_proxy(body.get("proxy"))
                else:
                    return self._json({"error": "未知动作"}, 400)
                return self._json({"ok": True, "result": res, "state": SVC.snapshot()})

            if path == "/api/shutdown":
                threading.Thread(target=lambda: (time.sleep(0.4), SVC.shutdown(), os._exit(0)), daemon=True).start()
                return self._json({"ok": True})
            
            if path == "/api/open-amane":
                os.startfile(SVC.amane_url()) if os.name == "nt" else None
                return self._json({"ok": True})

            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": str(e), "trace": traceback.format_exc()[-800:]}, 500)


def serve_panel() -> ThreadingHTTPServer:
    port = int(SVC.settings["panel_port"])
    host = str(SVC.settings.get("panel_host") or "127.0.0.1")
    httpd = ThreadingHTTPServer((host, port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    log("面板: http://%s:%d" % ("127.0.0.1" if host in ("0.0.0.0", "::", "") else host, port))
    return httpd


# ---------------------------------------------------------------- 系统托盘
#
# 管理器平时是 pythonw 跑的无窗口进程, 所以托盘图标就是它唯一的常驻入口。
# 零依赖: 用标准库 ctypes 直接调 Shell_NotifyIcon, 不装 pystray/Pillow;
# 图标= bin\tray_{on,off,err}.ico (缺失则退回系统默认图标)。
#
#   蓝(双向箭头) = 内核在跑   灰 = 已停止   红 = 启动失败
#   左键单击/双击 = 打开面板   右键 = 菜单(重启内核 / 同步域名 / 日志 / 退出)
# 悬停提示: AmaneProxy vX · 运行中 · 默认 日本

TRAY_ICON_DIR = APP_DIR / "bin"
TRAY_ICON_FILES = {"on": "tray_on.ico", "off": "tray_off.ico", "err": "tray_err.ico"}
TRAY: "TrayIcon | None" = None


def tray_notify(title: str, text: str, timeout_ms: int = 6000) -> None:
    """弹个气泡提示 (托盘没启用就静默忽略)。"""
    try:
        if TRAY is not None:
            TRAY.notify(title, text, timeout_ms)
    except Exception:
        pass


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _sh32 = ctypes.WinDLL("shell32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _LRESULT = ctypes.c_ssize_t
    _WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM)

    # ---- 常量 ----
    _WM_NULL, _WM_DESTROY, _WM_CLOSE = 0x0000, 0x0002, 0x0010
    _WM_TRAYICON = 0x8000 + 1               # WM_APP + 1
    _WM_LBUTTONUP, _WM_LBUTTONDBLCLK = 0x0202, 0x0203
    _WM_RBUTTONUP, _WM_CONTEXTMENU = 0x0205, 0x007B
    _NIM_ADD, _NIM_MODIFY, _NIM_DELETE = 0, 1, 2
    _NIF_MESSAGE, _NIF_ICON, _NIF_TIP, _NIF_INFO = 0x01, 0x02, 0x04, 0x10
    _NIIF_INFO = 0x01
    _IMAGE_ICON, _LR_LOADFROMFILE = 1, 0x10
    _IDI_APPLICATION = 32512
    _MF_STRING, _MF_GRAYED, _MF_SEPARATOR = 0x0, 0x1, 0x800
    _TPM_RIGHTBUTTON, _TPM_RETURNCMD = 0x02, 0x100
    _WS_POPUP = 0x80000000
    _SM_CXSMICON, _SM_CYSMICON = 49, 50
    _ERROR_CLASS_ALREADY_EXISTS = 1410

    class _WNDCLASSEXW(ctypes.Structure):
        # 注意: RegisterClassExW 认的是 WNDCLASSEX (首个字段是 cbSize);
        # 传 WNDCLASS 会让它把 style 当 cbSize 读 -> ERROR_INVALID_PARAMETER(87)。
        _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                    ("hIconSm", wintypes.HICON)]

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class _NOTIFYICONDATAW(ctypes.Structure):
        """Vista+ 的完整布局 (uVersion 与 uTimeout 是 union, 这里按 uVersion 用)。"""
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
                    ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                    ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                    ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                    ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", _GUID), ("hBalloonIcon", wintypes.HICON)]

    # 显式声明签名: 64 位下 HWND/LPARAM 不声明会被当成 int32 截断
    _u32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
    _u32.RegisterClassExW.restype = wintypes.ATOM
    _u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    _u32.CreateWindowExW.restype = wintypes.HWND
    _u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _u32.DefWindowProcW.restype = _LRESULT
    _u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _u32.GetMessageW.restype = wintypes.BOOL
    _u32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _u32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _u32.DispatchMessageW.restype = _LRESULT
    _u32.DestroyWindow.argtypes = [wintypes.HWND]
    _u32.PostQuitMessage.argtypes = [ctypes.c_int]
    _u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _u32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _u32.CreatePopupMenu.restype = wintypes.HMENU
    _u32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    _u32.DestroyMenu.argtypes = [wintypes.HMENU]
    _u32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    _u32.TrackPopupMenu.restype = ctypes.c_int
    _u32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
    _u32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _u32.GetSystemMetrics.restype = ctypes.c_int
    _u32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _u32.LoadImageW.restype = wintypes.HANDLE
    _u32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    _u32.LoadIconW.restype = wintypes.HANDLE
    _u32.DestroyIcon.argtypes = [wintypes.HICON]
    _u32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    _u32.RegisterWindowMessageW.restype = wintypes.UINT
    _k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _k32.GetModuleHandleW.restype = wintypes.HINSTANCE
    _sh32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]
    _sh32.Shell_NotifyIconW.restype = wintypes.BOOL
    _sh32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    _sh32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long

    # 窗口类只注册一次(进程级): WndProc 用模块级分发函数, 再转给"当前活动的 TrayIcon"。
    # 否则 stop() -> start() 重建实例时, 窗口类里还留着上一个实例的回调指针(已释放) -> 点图标会崩。
    _TRAY_STATE = {"active": None, "wp": None, "atom": 0}

    def _tray_dispatch(hwnd, msg, wparam, lparam):
        inst = _TRAY_STATE["active"]
        if inst is not None:
            return inst._wndproc(hwnd, msg, wparam, lparam)
        return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    class TrayIcon:
        """系统托盘图标 (状态色 + 右键菜单)。start() 之后在后台线程里跑消息循环。"""

        ID_OPEN_PANEL, ID_OPEN_AMANE = 1, 2
        ID_RESTART, ID_RELOAD, ID_SYNC, ID_PROBE, ID_LOGS, ID_QUIT = 3, 4, 5, 6, 7, 9
        STATE_WORDS = {"on": "● 运行中", "off": "○ 已停止", "err": "✕ 启动失败"}

        def __init__(self, service, title: str = "AmaneProxy"):
            self.svc = service
            self.title = title
            self.hwnd = None
            self._hicons: dict[str, int] = {}
            self._own_icons = False          # 从文件加载的图标才需要 DestroyIcon
            self._cls = "AmaneProxyTrayWnd"
            self._ready = threading.Event()
            self._stop = threading.Event()
            self._tab = 0
            self._tip_gen = 0
            self._thread: threading.Thread | None = None
            try:
                self._taskbar_msg = _u32.RegisterWindowMessageW("TaskbarCreated")
            except Exception:
                self._taskbar_msg = 0

        # ---------------- 状态 / 提示 ----------------

        def _state(self) -> str:
            try:
                if self.svc.running():
                    return "on"
            except Exception:
                return "err"
            return "err" if self.svc.error else "off"

        def _tooltip(self) -> tuple[str, str]:
            st = self._state()
            s = self.svc.settings
            cc = str(s.get("default_outbound") or "jp")
            out = {"auto": "自动", "direct": "直连"}.get(cc) or COUNTRY_NAMES.get(cc, cc)
            tip = "%s v%s · %s · 默认 %s" % (self.title, VERSION, self.STATE_WORDS[st][2:], out)
            if st != "on" and self.svc.error:
                tip += " · " + str(self.svc.error)[:60]
            return st, tip[:127]

        # ---------------- 图标 ----------------

        def _load_icons(self) -> None:
            cx = _u32.GetSystemMetrics(_SM_CXSMICON)
            cy = _u32.GetSystemMetrics(_SM_CYSMICON)
            for key, fname in TRAY_ICON_FILES.items():
                p = TRAY_ICON_DIR / fname
                if not p.exists():
                    continue
                h = _u32.LoadImageW(None, str(p), _IMAGE_ICON, cx, cy, _LR_LOADFROMFILE)
                if h:
                    self._hicons[key] = h
            if self._hicons:
                self._own_icons = True
                for key in TRAY_ICON_FILES:
                    self._hicons.setdefault(key, self._hicons.get("on"))
            else:
                log("托盘: 没找到 %s, 用系统默认图标" % TRAY_ICON_DIR)
                h = _u32.LoadIconW(None, ctypes.c_void_p(_IDI_APPLICATION))
                self._hicons = {k: h for k in TRAY_ICON_FILES}

        def _nid(self, flags: int) -> "_NOTIFYICONDATAW":
            nid = _NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = flags
            return nid

        def _add(self) -> bool:
            st, tip = self._tooltip()
            nid = self._nid(_NIF_MESSAGE | _NIF_ICON | _NIF_TIP)
            nid.uCallbackMessage = _WM_TRAYICON
            nid.hIcon = self._hicons.get(st) or self._hicons.get("on")
            nid.szTip = tip
            return bool(_sh32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid)))

        def _refresh(self) -> None:
            """按当前状态换图标颜色 + 刷新悬停文字。"""
            if not self.hwnd:
                return
            st, tip = self._tooltip()
            nid = self._nid(_NIF_ICON | _NIF_TIP)
            nid.hIcon = self._hicons.get(st) or self._hicons.get("on")
            nid.szTip = tip
            _sh32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(nid))

        def _del(self) -> None:
            if not self.hwnd:
                return
            _sh32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(self._nid(0)))

        def notify(self, title: str, text: str, timeout_ms: int = 6000) -> None:
            """气泡通知。"""
            if not self.hwnd:
                return
            nid = self._nid(_NIF_INFO)
            nid.uVersion = max(2000, int(timeout_ms))
            nid.szInfoTitle = str(title)[:63]
            nid.szInfo = str(text)[:255]
            nid.dwInfoFlags = _NIIF_INFO
            _sh32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(nid))

        # ---------------- 生命周期 ----------------

        def start(self) -> bool:
            if self._thread and self._thread.is_alive():
                return bool(self.hwnd)
            self._stop.clear()
            self._ready.clear()
            self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
            self._thread.start()
            self._ready.wait(6)
            if self.hwnd:
                self._tip_gen += 1
                threading.Thread(target=self._tip_loop, args=(self._tip_gen,),
                                 name="tray-tip", daemon=True).start()
            return bool(self.hwnd)

        def stop(self) -> None:
            self._tip_gen += 1          # 让旧的 tip 线程退出, 否则它会空转吃掉一个核
            self._stop.set()
            hwnd = self.hwnd
            try:
                self._del()
                if hwnd:
                    _u32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
            except Exception:
                pass
            if self._thread:
                self._thread.join(timeout=3)
            self.hwnd = None

        def _tip_loop(self, gen: int) -> None:
            while gen == self._tip_gen and not self._stop.is_set():
                try:
                    self._refresh()
                except Exception:
                    pass
                self._stop.wait(5)

        def _run(self) -> None:
            try:
                # 气泡通知的署名: 不设就是 "Python", 设了之后系统按 AmaneProxy 归类
                try:
                    _sh32.SetCurrentProcessExplicitAppUserModelID("AmaneProxy")
                except Exception:
                    pass
                hinst = _k32.GetModuleHandleW(None)
                if not _TRAY_STATE["atom"]:
                    if _TRAY_STATE["wp"] is None:
                        _TRAY_STATE["wp"] = _WNDPROC(_tray_dispatch)
                    wc = _WNDCLASSEXW()
                    wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
                    wc.lpfnWndProc = _TRAY_STATE["wp"]
                    wc.hInstance = hinst
                    wc.lpszClassName = self._cls
                    _TRAY_STATE["atom"] = _u32.RegisterClassExW(ctypes.byref(wc))
                    if not _TRAY_STATE["atom"] and ctypes.get_last_error() != _ERROR_CLASS_ALREADY_EXISTS:
                        log("托盘: 注册窗口类失败 (err=%d)" % ctypes.get_last_error())
                        return
                _TRAY_STATE["active"] = self
                self.hwnd = _u32.CreateWindowExW(0, self._cls, self.title, _WS_POPUP,
                                                 0, 0, 0, 0, None, None, hinst, None)
                if not self.hwnd:
                    log("托盘: 创建窗口失败")
                    return
                self._load_icons()
                if self._add():
                    log("托盘图标已就绪 (%s)" % ("bin\\tray_*.ico" if self._own_icons else "系统默认图标"))
                else:
                    log("托盘: Shell_NotifyIcon 失败 (err=%d)" % ctypes.get_last_error())
                self._ready.set()
                msg = wintypes.MSG()
                while _u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    _u32.TranslateMessage(ctypes.byref(msg))
                    _u32.DispatchMessageW(ctypes.byref(msg))
            except Exception as e:
                log("托盘异常: %s" % e)
            finally:
                self._ready.set()
                if _TRAY_STATE["active"] is self:
                    _TRAY_STATE["active"] = None
                try:
                    self._del()
                except Exception:
                    pass
                if self._own_icons:
                    for h in set(self._hicons.values()):
                        if h:
                            try:
                                _u32.DestroyIcon(h)
                            except Exception:
                                pass
                self._hicons = {}
                self.hwnd = None

        # ---------------- 消息 ----------------

        def _wndproc(self, hwnd, msg, wparam, lparam):
            try:
                if msg == _WM_TRAYICON:
                    ev = int(lparam) & 0xFFFF          # 未设 NIM_SETVERSION, lParam = 鼠标消息
                    if ev in (_WM_LBUTTONUP, _WM_LBUTTONDBLCLK):
                        self._act(self.ID_OPEN_PANEL)
                    elif ev in (_WM_RBUTTONUP, _WM_CONTEXTMENU):
                        self._popup()
                    return 0
                if self._taskbar_msg and msg == self._taskbar_msg:
                    self._add()                        # 资源管理器重启后把图标挂回去
                    return 0
                if msg == _WM_DESTROY:
                    _u32.PostQuitMessage(0)
                    return 0
                if msg == _WM_CLOSE:
                    _u32.DestroyWindow(hwnd)
                    return 0
            except Exception as e:
                log("托盘回调异常: %s" % e)
            return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)

        def _menu_item(self, text: str, mid: int = 0, flags: int = _MF_STRING) -> None:
            _u32.AppendMenuW(self._hmenu, flags, mid, text)

        def _popup(self) -> None:
            self._hmenu = _u32.CreatePopupMenu()
            if not self._hmenu:
                return
            s = self.svc.settings
            st = self._state()
            self._menu_item("打开面板", self.ID_OPEN_PANEL)
            self._menu_item("打开 Amane 网页", self.ID_OPEN_AMANE)
            self._menu_item("", 0, _MF_SEPARATOR)
            self._menu_item("状态: " + self.STATE_WORDS[st], 0, _MF_GRAYED)
            self._menu_item("入口 127.0.0.1:%s · 面板 %s" % (s.get("proxy_port"), s.get("panel_port")), 0, _MF_GRAYED)
            self._menu_item("", 0, _MF_SEPARATOR)
            self._menu_item("重启内核 (sing-box)", self.ID_RESTART)
            self._menu_item("重载规则并重启", self.ID_RELOAD)
            self._menu_item("立即同步域名", self.ID_SYNC)
            self._menu_item("测试三个出口", self.ID_PROBE)
            self._menu_item("", 0, _MF_SEPARATOR)
            self._menu_item("打开日志文件夹", self.ID_LOGS)
            self._menu_item("", 0, _MF_SEPARATOR)
            self._menu_item("退出 (停止代理并关闭管理器)", self.ID_QUIT)
            _u32.SetMenuDefaultItem(self._hmenu, self.ID_OPEN_PANEL, 0)
            pt = wintypes.POINT()
            _u32.GetCursorPos(ctypes.byref(pt))
            _u32.SetForegroundWindow(self.hwnd)         # 否则点空白处菜单不消失
            cmd = _u32.TrackPopupMenu(self._hmenu, _TPM_RIGHTBUTTON | _TPM_RETURNCMD,
                                      pt.x, pt.y, 0, self.hwnd, None)
            _u32.PostMessageW(self.hwnd, _WM_NULL, 0, 0)
            _u32.DestroyMenu(self._hmenu)
            if cmd:
                self._act(cmd)

        # ---------------- 动作 ----------------

        def _open(self, target: str) -> None:
            try:
                os.startfile(target)
            except Exception as e:
                log("打开 %s 失败: %s" % (target, e))

        def _act(self, cmd: int) -> None:
            if cmd == self.ID_OPEN_PANEL:
                self._open("http://127.0.0.1:%s" % self.svc.settings["panel_port"])
            elif cmd == self.ID_OPEN_AMANE:
                self._open(self.svc.amane_url())
            elif cmd == self.ID_RESTART:
                self._bg(self.svc.restart, "正在重启内核…")
            elif cmd == self.ID_RELOAD:
                self._bg(lambda: (self.svc.stop_singbox(), self.svc.start_singbox(), self.svc.probe_all()),
                         "正在重载配置…")
            elif cmd == self.ID_SYNC:
                self._bg(lambda: self.svc.sync_async(force=True), "正在同步域名…")
            elif cmd == self.ID_PROBE:
                self._bg(self.svc.probe_all, "正在测试出口…")
            elif cmd == self.ID_LOGS:
                self._open(str(LOGDIR))
            elif cmd == self.ID_QUIT:
                threading.Thread(target=self._quit, name="tray-quit", daemon=True).start()

        def _bg(self, fn, msg: str) -> None:
            """耗时动作丢到工作线程, 别卡住托盘消息循环。"""
            def job():
                self.notify(self.title, msg, 4000)
                try:
                    fn()
                except Exception as e:
                    log("托盘动作失败: %s" % e)
                    self.notify(self.title, "失败: " + str(e)[:150], 8000)
                else:
                    self.notify(self.title, msg.rstrip("…") + "完成", 3000)
                try:
                    self._refresh()
                except Exception:
                    pass
            threading.Thread(target=job, name="tray-job", daemon=True).start()

        def _quit(self) -> None:
            self.notify(self.title, "正在退出…", 2000)
            time.sleep(0.5)
            try:
                self.svc.shutdown()
            finally:
                os._exit(0)

else:
    class TrayIcon:  # 非 Windows: 空实现, 保证其余代码不用判断平台
        def __init__(self, service=None, title: str = "AmaneProxy"):
            self.svc = service
            self.hwnd = None

        def start(self) -> bool:
            return False

        def stop(self) -> None:
            pass

        def notify(self, *a, **k) -> None:
            pass


def set_tray(enabled: bool) -> bool:
    """运行时开/关托盘图标 (面板勾选项 / 命令行)。"""
    global TRAY
    if enabled:
        if TRAY is None:
            TRAY = TrayIcon(SVC)
        ok = TRAY.start()
        if not ok:
            TRAY = None
        log("托盘图标: " + ("已打开" if ok else "打开失败"))
        return ok
    if TRAY is not None:
        TRAY.stop()
        TRAY = None
        log("托盘图标: 已关闭")
    return False


def pid_alive(pid: int) -> bool:
    """进程是否还活着 (跨平台)。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace",
                                 creationflags=CREATE_NO_WINDOW, timeout=15).stdout
            return str(pid) in (out or "")
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def pid_is_amaneproxy(pid: int) -> bool:
    """确认这个 pid 真的是本程序。容器重启后 /data 里的旧 pid 可能撞上别的进程。"""
    alive = pid_alive(pid)
    if not alive or os.name == "nt":
        return alive
    try:
        cmdline = Path("/proc/%d/cmdline" % pid).read_bytes().decode("utf-8", "replace")
    except Exception:
        return True          # 读不到 /proc 就保守当它是自己
    return "amaneproxy" in cmdline


def kill_pid(pid: int, tree: bool = True) -> bool:
    """结束进程 (Windows 走 taskkill; POSIX 先 SIGTERM 再 SIGKILL)。"""
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name == "nt":
        args = ["taskkill", "/PID", str(pid)] + (["/T"] if tree else []) + ["/F"]
        subprocess.run(args, capture_output=True, creationflags=CREATE_NO_WINDOW)
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        return False
    for _ in range(30):
        if not pid_alive(pid):
            return True
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass
    return True


# ---------------------------------------------------------------- 入口


def cmd_status() -> int:
    st = None
    if not SVC.running():
        # 常驻的管理器在别的进程里 (Docker / 无窗口运行) —— 直接问面板, 否则会误报成"没运行"
        try:
            st = http_json("http://127.0.0.1:%d/api/state" % int(SVC.settings["panel_port"]), timeout=6)
        except Exception:
            st = None
    if st is None:
        st = SVC.snapshot()
    print(json.dumps({
        "running": st["running"], "entry": st["ports"]["entry"], "panel": st["ports"]["panel"],
        "selectors": st["selectors"],
        "probe": {k: {"ok": v.get("ok"), "ip": v.get("ip"), "country": v.get("country"), "ms": v.get("ms")}
                  for k, v in st["probe"].items()},
        "amane": st["amane"],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_stop() -> int:
    killed = False
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text().strip())
            kill_pid(pid, tree=True)
            killed = True
        except Exception as e:
            print("停止失败:", e)
    if SB_PID_PATH.exists():
        try:
            kill_pid(int(SB_PID_PATH.read_text().strip()), tree=False)
        except Exception:
            pass
    print("已停止" if killed else "没有找到运行中的管理器 (pid 文件不存在)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Amane 代理调度器")
    ap.add_argument("--stop", action="store_true", help="停止正在运行的管理器")
    ap.add_argument("--status", action="store_true", help="打印状态")
    ap.add_argument("--restart", action="store_true", help="重启 sing-box 后退出")
    ap.add_argument("--verbose", action="store_true", help="日志同时打到控制台")
    ap.add_argument("--no-start", action="store_true", help="不自动启动 sing-box")
    ap.add_argument("--no-tray", action="store_true", help="不显示系统托盘图标")
    args = ap.parse_args()

    SVC.verbose = args.verbose
    SVC.bootstrap_files()

    if args.stop:
        return cmd_stop()
    if args.status:
        return cmd_status()
    if args.restart:
        SVC.restart()
        return 0

    # 单实例: 已有管理器在跑就不重复起
    if PID_PATH.exists():
        try:
            old = int(PID_PATH.read_text().strip())
            if old != os.getpid() and pid_is_amaneproxy(old):
                print("管理器已在运行 (pid %d), 面板 http://127.0.0.1:%s" % (old, SVC.settings["panel_port"]))
                return 0
        except Exception:
            pass
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")

    for port_name, port in (("面板", SVC.settings["panel_port"]), ("入口", SVC.settings["proxy_port"]),
                            ("clash API", SVC.settings["clash_port"])):
        if not port_free(int(port)):
            msg = "%s端口 %s 已被占用" % (port_name, port)
            print(msg)
            log(msg)

    if not args.no_start:
        try:
            SVC.start_singbox()
        except Exception as e:
            SVC.error = str(e)
            log("启动失败: %s" % e)

    if not args.no_tray and SVC.settings.get("tray", True):
        global TRAY
        TRAY = TrayIcon(SVC)
        if TRAY.start():
            tray_notify("AmaneProxy", "已在托盘运行 · 右键看菜单", 3000)
        else:
            TRAY = None
            log("托盘图标不可用, 仅面板模式 (http://127.0.0.1:%s)" % SVC.settings["panel_port"])

    httpd = serve_panel()
    threading.Thread(target=SVC.health_loop, daemon=True).start()
    threading.Thread(target=SVC.watchdog_loop, daemon=True).start()
    threading.Thread(target=SVC.sync_loop, daemon=True).start()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *a: (SVC.shutdown(), os._exit(0)))
        except Exception:
            pass
    log("管理器就绪 v%s (pid %d)" % (VERSION, os.getpid()))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        SVC.shutdown()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log("致命错误:\n" + traceback.format_exc())
        raise
