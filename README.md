# AmaneProxy · 本地分流代理调度器

给 [Amane](https://github.com/sqzw-x/amane) 用的**本地代理调度器**：本机跑一个 sing-box 内核，
把 Amane 的 `network.proxy` 指向它，就能做到

- **按目标网站自动走不同出口**：日本站 → 日本出口，欧美站 → 美国出口，韩国站 → 韩国出口，其余走默认出口；
- **出口故障自动转移**：某条出口挂了自动切到健康的，恢复后自动切回；
- **定时同步站点域名**：站点换域名时自动补分流规则，避免流量掉到默认出口；
- **出口实测调优**：某个域名在原出口不通时，实测其它出口并自动改走能通的那个；
- 本地面板 + **系统托盘图标**，日常不用碰命令行。

[![docker build](https://github.com/maxuanp/AmaneProxy/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/maxuanp/AmaneProxy/actions/workflows/docker-publish.yml)
**当前版本 v1.4.0** · [更新日志](CHANGELOG.md) · [Releases](https://github.com/maxuanp/AmaneProxy/releases) ·
容器镜像 `ghcr.io/maxuanp/amaneproxy` · 本程序 **MIT** 许可（内置的 sing-box 内核为 GPL-3.0）

> **适合谁**：用 Amane 捣削元数据/看图，但不同站点要求不同地区出口的人；
> 或者手上有日/韩/美多个节点，想让不同网站自动走对应出口、连接挂了还能自己切回来的人。

### 两种跑法，选一个就够

| | **Windows 桌面版** | **Docker 版**（Linux / NAS / Docker Desktop） |
|---|---|---|
| 需要什么 | Windows 10/11 + Python 3.10+ | 只要 Docker |
| 内核 | 随包自带 / `setup.py` 自动下载 | 构建镜像时自动取（有内网加速方案） |
| 界面 | 面板 + **系统托盘图标** | 面板，`http://127.0.0.1:18111` |
| 数据在哪 | 程序目录 | 一个卷（容器里 `/data`） |
| 在哪看 | 任务栏右下角托盘 | `docker compose logs -f` |

```bash
# ——— Docker 版（细节看第 3 节）
docker compose up -d          # 然后开 http://127.0.0.1:18111 ，在「总览 → 出口管理」填自己的节点
```

```powershell
# ——— Windows 版（细节看第 2 节）
双击 install.cmd              # 等价于 setup.py + 开机自启 + 立即启动
```

> 本仓库**不含任何节点/服务器信息、不含任何使用记录**：`servers.json`、`amaneproxy.json`、
> 分流规则、日志都是首次运行时在本机生成的默认文件，你需要自己填自己的出口。

---

## 目录

- [1. 系统要求](#1-系统要求)
- [2. 快速开始（Windows）](#2-快速开始)
- [3. Docker 部署](#3-docker-部署可选)
- [4. 配置你自己的出口](#4-配置你自己的出口)
- [5. 把 Amane 接进来](#5-把-amane-接进来)
- [6. 面板说明](#6-面板说明)
- [7. 托盘图标](#7-托盘图标)
- [8. 常用命令](#8-常用命令)
- [9. 端口](#9-端口)
- [10. 常见问题](#10-常见问题)
- [11. 文件清单](#11-文件清单)
- [12. 隐私与安全](#12-隐私与安全)
- [13. 声明](#13-声明)
- [更新日志 CHANGELOG.md](CHANGELOG.md)

---

## 1. 系统要求

**Windows 桌面版**

- Windows 10 / 11（x64）+ **Python 3.10+**（只用标准库，不用 pip 装任何东西；安装时记得勾上 *Add python.exe to PATH*）
- 一个能用的代理出口：自己的 VPS 节点、机场订阅里的 hysteria2 / shadowsocks，或者本机已经在跑的代理客户端
- 内核：完整包自带 sing-box；精简包没有，`setup.py` 会自动去 GitHub 下（国内可以先准备一个能用的代理，
  或手动把内核放进 `bin\`）

**Docker 版**

- 任何能跑 Docker 的 Linux / NAS / Docker Desktop，**不用装 Python**，镜像自带内核（构建细节见第 3 节）

## 2. 快速开始

解压到**任意目录**（路径里尽量别有中文/空格，例如 `D:\AmaneProxy`），然后：

```
双击 install.cmd          # 一键：初始化文件 + 装开机自启 + 立刻启动
```

面板地址：**http://127.0.0.1:18111**　托盘图标在任务栏右下角（Win11 可能收在 `^` 里）。

不想用一键脚本的话，手动三步：

```powershell
python setup.py --root "D:\AmaneProxy"      # ① 初始化（缺内核会去下载）
powershell -File "D:\AmaneProxy\install-autostart.ps1"   # ② 可选：开机自启 + 守护
wscript "D:\AmaneProxy\start.vbs"           # ③ 启动（无窗口）
```

> 脚本里的路径都是**相对脚本自身**的，整个文件夹可以随便移动/改名，改完重新跑一次
> `install-autostart.ps1` 即可修好自启快捷方式。

## 3. Docker 部署（可选）

不想装 Python、或者想在 NAS / 服务器的 Linux 上跑，用 Docker 最省事：镜像里自带 sing-box 内核，
配置 / 规则 / 日志都放在一个卷里，升级镜像不会丢。

```bash
# 方式一：compose（推荐）
docker compose up -d
docker compose logs -f

# 方式二：直接跑
docker build -t amaneproxy .
docker run -d --name amaneproxy --restart unless-stopped \
  -p 127.0.0.1:18110:18110 -p 127.0.0.1:18111:18111 \
  --add-host host.docker.internal:host-gateway \
  -e AMANEPROXY_AMANE_URL=http://host.docker.internal:18100 \
  -v amaneproxy-data:/data \
  amaneproxy
```

面板同样是 **http://127.0.0.1:18111**，出口配置和 Windows 版一模一样（面板 → 总览 → 出口管理）。

> ⚠️ 面板本身**没有鉴权**（桌面版靠只监听 `127.0.0.1` 兜底）。放到远程服务器上时，
> `ports:` 里面板那行别写成 `0.0.0.0:18111:18111` 直接怼到公网；要远程看面板就走 SSH 隧道：
> `ssh -L 18111:127.0.0.1:18111 用户@服务器`，然后本地开 http://127.0.0.1:18111 。

> 本节内容是实测过的：在 Ubuntu 22.04 + Docker 20.10（经典 builder）上真跑通了
> 构建镜像 → 起容器 → 面板 API → **宿主经 18110 端口映射走代理拿到 200** → 健康检查 healthy
> → `docker stop` 干净退出 → 空卷首启自动生成模板并可从面板加出口，内核版本 sing-box 1.14.2。

### 3.1 和 Windows 版的区别

| | Windows 版 | Docker 版 |
|---|---|---|
| 内核 | `bin\sing-box.exe`（随包 / `setup.py` 下载） | `/usr/local/bin/sing-box`（构建镜像时下载） |
| 配置/规则/日志 | 程序目录 | `/data`（**必须挂卷**，否则重建容器就没了） |
| 监听地址 | `127.0.0.1` | `0.0.0.0` + 端口映射（默认只映到宿主 `127.0.0.1`，不对外暴露） |
| 托盘图标 | 有 | 无（容器里没有桌面；`AMANEPROXY_TRAY=0`，面板里这项也会显示成关闭） |
| Amane 的 API 地址 | `127.0.0.1:18100` | `host.docker.internal:18100` |

### 3.2 环境变量

环境变量**优先于** `amaneproxy.json`，而且不会被写回文件（同一份镜像不改配置就能跑）。

| 变量 | 镜像里的默认值 | 说明 |
|---|---|---|
| `AMANEPROXY_HOME` | `/data` | 数据目录（配置 / 规则 / 日志 / pid） |
| `AMANEPROXY_SINGBOX` | `/usr/local/bin/sing-box` | 内核路径 |
| `AMANEPROXY_PROXY_PORT` | `18110` | 代理入口端口 |
| `AMANEPROXY_PANEL_PORT` | `18111` | 面板端口 |
| `AMANEPROXY_CLASH_PORT` | `18112` | 内核 clash API（内部热切换用） |
| `AMANEPROXY_LISTEN_HOST` | `0.0.0.0` | 代理入口监听地址（容器里必须 `0.0.0.0` 才能被映射出去） |
| `AMANEPROXY_PANEL_HOST` | `0.0.0.0` | 面板监听地址 |
| `AMANEPROXY_AMANE_URL` | `http://host.docker.internal:18100` | 宿主机上 Amane 的 API 地址 |
| `AMANEPROXY_AMANE_TOKEN` | 空 | 直接给 Amane 的 token（省得挂载文件） |
| `AMANEPROXY_AMANE_TOKEN_FILE` | 空 | token 文件路径，例：`/data/amane-token` |
| `AMANEPROXY_TRAY` | `0` | 容器里关掉托盘 |
| `AMANEPROXY_DEFAULT_OUTBOUND` | 空 | 默认出口：`jp` / `kr` / `us` / `auto` / `direct` |
| `TZ` | `UTC` | 日志时间，例：`Asia/Shanghai` |

### 3.3 让 Amane 走容器里的调度器

1. 在**宿主机**的 Amane 里把 `network.proxy` 填 `http://127.0.0.1:18110`
   （容器把 18110 映到了宿主回环，所以还是 `127.0.0.1`，**别写容器名/容器 IP**）。
   直接在面板点「让 Amane 走本调度器」写的也是这个值，对宿主机来说正好。
2. 面板的「Amane 集成」需要读宿主 Amane 的 token，二选一：
   - **挂载 token 文件**（compose 里有注释示例）：
     `- C:/Users/你的用户名/AppData/Local/Amane/token:/data/amane-token:ro`
     （Linux 宿主是 `~/.local/share/Amane/token`，Docker 里也认 `/data/amane-token`）
   - **或直接传环境变量**：`-e AMANEPROXY_AMANE_TOKEN=<token 内容>`
3. Amane 那边如果报网络超时，把它的 `network.timeout` 调大（比如 30 秒），走代理首包会慢一点。

> **Linux 宿主还可以用 host 网络**：compose 里写 `network_mode: host`，容器和宿主共用网络栈，
> 此时 `AMANEPROXY_LISTEN_HOST` / `AMANEPROXY_PANEL_HOST` 保持 `127.0.0.1`，
> `AMANEPROXY_AMANE_URL` 也能直接用 `http://127.0.0.1:18100`。host 模式下 `ports:` 不生效。

### 3.4 构建镜像

镜像里**不需要用 apt**：python 官方 slim 镜像自带 ca-certificates 和 zoneinfo，取内核用的是镜像里现成的
python（`docker/get-kernel.py`）；Dockerfile 也故意没写 `# syntax=` 指令，免得 BuildKit 先去 Docker Hub 拉
frontend 镜像。所以国内构建只需要两样通：**拉得到 python 基础镜像** + **下得到内核包**。

```bash
# 最普通（GitHub 直连没问题时）
docker build -t amaneproxy .
```

国内实测最顺的做法（在 Ubuntu 22.04 + Docker 20.10 上验证过）：

```bash
docker build \
  --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim \
  --build-arg SINGBOX_URL='https://gh-proxy.com/https://github.com/SagerNet/sing-box/releases/download/v1.14.2/sing-box-1.14.2-linux-amd64.tar.gz' \
  -t amaneproxy .
# 实测 35 秒（30MB 内核走加速站 4 秒），镜像 209MB，内核 sing-box 1.14.2
```

下不动 GitHub 时的三条退路（按推荐顺序）：

1. **手动下好内核包放进 `docker/`**，构建时直接用、**完全不联网**（实测 11 秒构建完）：
   ```bash
   # 文件名任意，只要是 sing-box*.tar.gz；也可以直接放二进制、命名成 docker/sing-box
   # 拿包的例子（浏览器/能上 GitHub 的机器都行）：
   #   https://gh-proxy.com/https://github.com/SagerNet/sing-box/releases/download/v1.14.2/sing-box-1.14.2-linux-amd64.tar.gz
   docker/sing-box-1.14.2-linux-amd64.tar.gz
   docker build -t amaneproxy .
   ```
2. **给下载挂加速前缀**：`--build-arg SINGBOX_URL='https://gh-proxy.com/https://github.com/...'`
   （实测可用；顺带一提 `ghfast.top` 实测只有几 KB/s，不要用）。
3. **走代理**：`--build-arg HTTP_PROXY=http://你的代理:端口`
   （`get-kernel.py` 用 urllib 下载，会自动读取这个变量）。

其它构建参数：

```bash
docker build --build-arg PYTHON_IMAGE=<镜像站>/library/python:3.12-slim -t amaneproxy .  # 换基础镜像源
docker build --build-arg SINGBOX_VERSION=1.14.2 -t amaneproxy .                          # 固定内核版本
```

多架构（amd64 / arm64）镜像由 GitHub Actions 自动构建并推到 `ghcr.io/maxuanp/amaneproxy`
（见 `.github/workflows/docker-publish.yml`，里面还有一个「把容器真起起来、面板 API 能通」的冒烟任务），
所以也可以直接：

```bash
docker run -d --name amaneproxy --restart unless-stopped \
  -p 127.0.0.1:18110:18110 -p 127.0.0.1:18111:18111 \
  --add-host host.docker.internal:host-gateway \
  -v amaneproxy-data:/data ghcr.io/maxuanp/amaneproxy:latest
```

### 3.5 排错

```bash
docker compose logs -f                                          # 管理器日志（容器以 --verbose 跑）
docker compose exec amaneproxy tail -f /data/logs/sing-box.log   # 内核日志
docker compose exec amaneproxy cat /data/amaneproxy.json         # 当前设置
docker compose exec amaneproxy python /app/amaneproxy.py --status # 命令行看状态
```

- **出口都「不可用」**：多半是出口填错（服务器/端口/密码/SNI），或者本机根本没有对应代理客户端；
  看 `/data/logs/sing-box.log`。首次跑用默认模板（指向 `127.0.0.1:1080` 的示例出口）时内核是能正常起的，
  只是探测不到出口 IP，属正常现象。
- **`/data` 是空的 / 配置每次都没了**：卷没挂上。
- **面板打不开**：确认 `ports:` 里映的是面板端口，且 `AMANEPROXY_PANEL_HOST=0.0.0.0`。
- **`docker stop` 会不会留残留进程**：不会。管理器收到 SIGTERM 会先停内核再退出
  （实测 1 秒、退出码 0，日志里能看到「sing-box 已停止 / 管理器退出」）。

## 4. 配置你自己的出口

启动后打开面板 → **总览 → 出口管理**：

| 类型 | 需要的字段 | 说明 |
|---|---|---|
| `hysteria2` | 服务器、端口、SNI、密码 | 机场/自建 hy2 节点。SNI 就是服务端证书用的域名；自签证书勾「跳过证书」 |
| `shadowsocks` | 服务器、端口、加密方式、密码 | 常规 SS 节点（sing-box 不支持 SSR 的 `auth_chain_a` 等私有协议，那种只能用本机客户端） |
| `socks` | 服务器、端口 | 指向**本机已有的代理客户端**（例：Clash/v2rayN/SSR 客户端的 socks5 端口 1080） |

要点：

- 每个出口有个 `cc`（国家代码：`jp`/`kr`/`us`…）。**分流规则是按国家代码找出口的**，
  所以想让「日本站走日本」，就得有一个 `cc = jp` 的出口；没有对应出口时，那些域名会自动直连。
- 同一个 `cc` 可以放多台（比如日本既有新 hy2 又有旧客户端），**排在前面的就是默认**；
  想换主出口，改顺序或直接在面板上手动切换。
- 面板「总览」里能看到每个出口实测的出口 IP / 国家 / 延迟；「默认出口」下拉框决定没命中规则的域名走哪儿
  （可设 `自动`＝在可用出口里挑最快、或 `直连`）。

## 5. 把 Amane 接进来

面板 → **Amane 集成** → 点「让 Amane 走本调度器」。它会替你改 Amane 的 `network.proxy`，
并记住改之前的值，随时可以「还原」。

> 注意必须是 `http://127.0.0.1:18110`，**不能用 `socks5://`**：
> 走 SOCKS5 时 client 会先在本地解析域名再交给代理，按域名分流就失效了（DNS 被污染时拿到的 IP 也没用）；
> HTTP CONNECT 会把域名原样带过去。

## 6. 面板说明

- **总览**：默认出口 / 故障自动转移开关 / 系统托盘图标开关 / 各出口实测状态 / 出口管理 / 自动转移记录
- **分流规则**：一键预设（日本站、欧美站）、按域名后缀/完整域名/关键字/正则新增规则、分流自检
- **域名同步**：定时从 Amane 的源配置 + 站点跳转里取最新域名补规则；出口实测调优开关
- **Amane 集成**：接入 / 还原 / 自定义 `network.proxy`
- **日志**：调度器日志 + 内核日志

## 7. 托盘图标

管理器平时是**无窗口**进程，托盘就是它唯一的常驻入口：

| 图标 | 含义 |
|---|---|
| 蓝（双向箭头） | 内核在跑，分流生效 |
| 灰 | 已停止 |
| 红 | 启动失败（悬停提示里有原因） |

- 左键单击/双击 = 打开面板；右键 = 菜单：打开面板 / 打开 Amane 网页 / 重启内核 / 重载规则并重启 /
  立即同步域名 / 测试三个出口 / 打开日志文件夹 / 退出
- 悬停显示当前状态、默认出口
- 不想要：面板「总览」取消勾选「系统托盘图标」，或启动时加 `--no-tray`
- **Windows 11**：新图标默认被收进任务栏右下角的 `^` 溢出区，
  `设置 → 个性化 → 任务栏 → 其他系统托盘图标 → AmaneProxy` 打开即可常显

## 8. 常用命令

```powershell
wscript start.vbs                        # 启动（无窗口）
powershell -File status.ps1              # 看状态（出口 IP / 国家 / 延迟）
powershell -File stop.ps1                # 停止（管理器 + 内核）
powershell -File ensure.ps1              # 没在跑就拉起
powershell -File install-autostart.ps1   # 装开机自启 + 每 5 分钟守护
powershell -File uninstall-autostart.ps1 # 取消开机自启
python amaneproxy.py --status            # 命令行看状态
python amaneproxy.py --no-tray           # 不要托盘图标
python amaneproxy.py --verbose           # 前台跑并打印日志（排查用）
```

## 9. 端口

| 用途 | 端口 |
|---|---|
| 代理入口（socks5 + http 混合，给 Amane 用） | 127.0.0.1:18110 |
| 本地面板 | 127.0.0.1:18111 |
| 内核 clash API（内部热切换用） | 127.0.0.1:18112 |
| 每个出口的探测入口 | 18211、18212…（按出口顺序往后排） |

端口都能在面板里改（`panel_port` / `proxy_port` / `clash_port`），也可以用环境变量覆盖
（`AMANEPROXY_PROXY_PORT` / `AMANEPROXY_PANEL_PORT` / `AMANEPROXY_CLASH_PORT`）。
桌面版**只监听 127.0.0.1，不对外暴露**；Docker 版默认也只把端口映到宿主的 `127.0.0.1`。

### 更新到新版本

```powershell
# Windows：解压新版覆盖过去就行（servers.json / amaneproxy.json / rules.json / logs 不会被覆盖），
# 然后 powershell -File install-autostart.ps1 修一下自启快捷方式
```

```bash
# Docker：换镜像重启，数据都在卷里
docker compose pull && docker compose up -d
# 或者 docker build -t amaneproxy . && docker compose up -d --force-recreate
```

版本历史见 [CHANGELOG.md](CHANGELOG.md)，新版本会在 [Releases](https://github.com/maxuanp/AmaneProxy/releases) 里发。

## 10. 常见问题

- **面板打不开**：`powershell -File status.ps1` 看有没有在跑；`logs\amaneproxy.log` 有日志。
- **托盘是红色**：内核没起来。多半是出口填错（服务器/密码/SNI），或端口被别的程序占了，
  看面板日志里 sing-box 的报错；也可以 `python amaneproxy.py --verbose` 前台跑一次。
- **某个出口显示不可用**：先确认节点自身能用；日本节点如果在你本机是 SSR 协议，请用 `socks` 类型指向你客户端的端口。
- **`setup.py` 下载内核失败**：手动下载 sing-box 的 `windows-amd64` 压缩包，
  把 `sing-box.exe`、`libcronet.dll`、`LICENSE` 放进 `bin\`，然后重新运行 `install.cmd`。
- **Amane 那边报网络错误**：Amane 自身也有个网络超时（默认 10 秒），走代理的首包可能更慢 ——
  如果经常超时，把 Amane 的 `network.timeout` 调大一些（例如 30）。

**Docker 相关**

- **`docker build` 卡在拉基础镜像**：换镜像站
  `--build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim`。
- **`docker build` 卡在下内核**（日志停在 `>>> 下载内核: ...`）：给下载挂加速前缀
  `--build-arg SINGBOX_URL='https://gh-proxy.com/https://github.com/SagerNet/sing-box/releases/download/v1.14.2/sing-box-1.14.2-linux-amd64.tar.gz'`，
  或者手动下好内核包丢进 `docker/` 目录——那就是**完全离线构建**，实测 11 秒。
- **容器里的 127.0.0.1 不是宿主机**：接入宿主 Amane 要用 `AMANEPROXY_AMANE_URL=http://host.docker.internal:18100`；
  反过来，Amane 的 `network.proxy` 还是填 `http://127.0.0.1:18110`（那是端口映射到宿主回环的）。
- **面板从别的机器打不开**：默认只绑宿主 `127.0.0.1`。要么改 compose 里的端口映射为 `18111:18111`，
  要么走 SSH 隧道（面板没有鉴权，别直接对公网开）。

## 11. 文件清单

```
AmaneProxy\
  amaneproxy.py           管理器本体：生成 sing-box 配置 / 进程守护 / 探测 / 故障转移 / 托盘 / 面板 / Amane 集成
  panel.html              面板 UI
  setup.py                初始化：复制文件 / 下载内核 / 生成 servers.json
  Dockerfile              Docker 镜像（多阶段：取 Linux 内核 + Python 运行时）
  docker-compose.yml      compose 编排（端口/卷/环境变量都在这里改）
  docker/get-kernel.py    构建期取内核（不用 apt/curl，只用镜像里的 python；支持加速前缀/预置包）
  docker/entrypoint.sh    容器入口（准备数据目录 + 接入提示）
  .github/workflows/docker-publish.yml   推 main/tag 时自动构建 amd64+arm64 镜像到 ghcr.io，并跑容器冒烟测试
  CHANGELOG.md            更新日志
  install.cmd             一键安装（初始化 + 自启 + 启动）
  start.vbs               无窗口启动
  ensure.ps1              守护：没在跑就拉起（配计划任务，每 5 分钟）
  status.ps1 / stop.ps1   看状态 / 停止
  install-autostart.ps1 / uninstall-autostart.ps1   装 / 卸 开机自启
  bin\sing-box.exe        内核（官方 release，GPL-3.0，许可见 bin\LICENSE）
  bin\libcronet.dll       内核自带依赖
  bin\tray_on/off/err.ico 托盘图标
  —— 下面是首次运行时自动生成的，不属于压缩包 ——
  servers.json            出口定义（**明文存密码**，别外传）
  rules.json              分流规则
  amaneproxy.json         设置
  config.json             生成的 sing-box 配置
  logs\                   日志（里面会有你访问过的域名，别外传）
```

## 12. 隐私与安全

本节针对「把仓库 / 安装目录分享出去」这件事，发布前逐项扫过（文件内容 + 全部 git 历史）：

**仓库里没有的**

- 没有任何节点地址、端口、密码、订阅链接、token、API key、私钥；
- 没有 `servers.json` / `amaneproxy.json` / `config.json` / `rules.json` / `logs\` ——
  这些都是**首次运行时在你本机生成**的，所以仓库里没有任何使用记录、也没有你访问过的域名；
- 没有开发者的个人路径、用户名、邮箱、机器名：脚本一律用 `$PSScriptRoot` / `ScriptFullName`
  取自己所在目录，不写死盘符。

**运行时要注意的**

- 所有服务默认只监听 `127.0.0.1`，不对外提供端口（Docker 版默认也只把端口映射到宿主的回环地址）；
- 面板**没有鉴权**，别把它直接暴露到公网；要远程看就开 SSH 隧道；
- `servers.json` 是**明文**保存节点密码的（和多数代理客户端一样），`logs\` 里会记录你访问过的域名。
  分享自己的整份安装目录（或 Docker 的数据卷）前，删掉 `servers.json`、`amaneproxy.json`、`config.json`、`logs\`；
- 内核 sing-box 由 [SagerNet](https://github.com/SagerNet/sing-box) 提供（GPL-3.0），许可见它自己的 LICENSE；
  本程序自身是 **MIT** 许可。

## 13. 声明与 AI 参与说明

**AI 参与情况（如实说明）**

- 本项目是**作者 + AI 协作**的产物：需求、取舍、测试、发布由作者负责，代码与文档的大量内容由 AI 辅助生成或修改。
- 用过的模型：DeepSeek 系列——早期版本由 “DeepSeek4.1 flash” 辅助生成；
  v1.4.0 的 Docker 支持与本文档的这次改版由 AI 助手（Chatbox + DeepSeek）完成。
- v1.4.0 是**在真机上验证过**才发布的：Ubuntu 22.04 + Docker 20.10（经典 builder），
  构建 → 起容器 → 面板 API → 宿主经端口映射走代理拿到 200 → 健康检查 healthy → `docker stop` 干净退出，
  内核 sing-box 1.14.2。
- AI 生成的内容**不保证没有错误**。请把它当工具用，别当经过安全审计的产品；上线前自己过一眼配置
  （出口凭据、绑定地址、面板暴露范围）。
- AI 参与**不影响许可**：本程序是 MIT（见 `LICENSE`）；内置 / 下载的 sing-box 内核仍为 GPL-3.0。

**免责**

- 本程序只是一个**本地代理调度器**：不提供任何节点、订阅或加速服务，能不能访问某个站点取决于你自己的出口。
- 请遵守你所在地区的法律法规和目标站点的服务条款，使用本程序所产生的一切后果由使用者自负。
- 日志会记录访问过的域名，请自行保管好安装目录 / 数据卷。

---
本程序由 DeepSeek 系列模型辅助生成与维护（详见上面的「AI 参与说明」）。
