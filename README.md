# AmaneProxy · 本地分流代理调度器

为 [Amane](https://github.com/sqzw-x/amane) 提供的**本地代理调度器**：在本机运行一个 sing-box 内核，
并将 Amane 的 `network.proxy` 指向它，即可实现：

- **按目标站点自动分流**：日本站点 → 日本出口，欧美站点 → 美国出口，韩国站点 → 韩国出口，其余域名走默认出口；
- **出口故障自动转移**：某出口不可用时自动切换至健康出口，恢复后自动切回；
- **定时同步站点域名**：站点更换域名时自动补充分流规则，避免流量落入默认出口；
- **出口实测调优**：某域名在原出口不可达时，实测其它出口并自动切换至可达者；
- 提供本地 Web 面板与**系统托盘图标**，日常操作无需使用命令行。

[![docker build](https://github.com/maxuanp/AmaneProxy/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/maxuanp/AmaneProxy/actions/workflows/docker-publish.yml)
**当前版本 v1.4.0** · [更新日志](CHANGELOG.md) · [Releases](https://github.com/maxuanp/AmaneProxy/releases) ·
容器镜像 `ghcr.io/maxuanp/amaneproxy` · 本程序 **MIT** 许可（内置的 sing-box 内核为 GPL-3.0）

> **适用场景**：使用 Amane 刮削元数据或浏览图片，而不同站点要求不同地区出口的用户；
> 或已持有日本 / 韩国 / 美国等多个节点，希望不同网站自动使用对应出口、链路故障时自动切换的用户。

### 两种部署方式

| | **Windows 桌面版** | **Docker 版**（Linux / NAS / Docker Desktop） |
|---|---|---|
| 前置条件 | Windows 10 / 11 + Python 3.10+ | 仅需 Docker |
| 内核来源 | 安装包内置，或由 `setup.py` 自动下载 | 构建镜像时自动获取（支持国内加速） |
| 界面 | Web 面板 + **系统托盘图标** | Web 面板（`http://127.0.0.1:18111`） |
| 数据位置 | 程序目录 | 数据卷（容器内 `/data`） |
| 运行日志 | 托盘菜单 / 日志目录 | `docker compose logs -f` |

```bash
# ——— Docker 版（详见第 3 节）
docker compose up -d          # 随后打开 http://127.0.0.1:18111，在「总览 → 出口管理」中填写节点信息
```

```powershell
# ——— Windows 版（详见第 2 节）
双击 install.cmd              # 相当于 setup.py + 开机自启 + 立即启动
```

> 本仓库**不含任何节点 / 服务器信息，也不含任何使用记录**：`servers.json`、`amaneproxy.json`、
> 分流规则与日志均为首次运行时在本机生成的默认文件，出口信息需自行填写。

---

## 目录

- [1. 系统要求](#1-系统要求)
- [2. 快速开始（Windows）](#2-快速开始)
- [3. Docker 部署](#3-docker-部署可选)
- [4. 配置代理出口](#4-配置代理出口)
- [5. 将 Amane 接入本调度器](#5-将-amane-接入本调度器)
- [6. 面板说明](#6-面板说明)
- [7. 托盘图标](#7-托盘图标)
- [8. 常用命令](#8-常用命令)
- [9. 端口](#9-端口)
- [10. 常见问题](#10-常见问题)
- [11. 文件清单](#11-文件清单)
- [12. 隐私与安全](#12-隐私与安全)
- [13. 声明与 AI 参与说明](#13-声明与-ai-参与说明)
- [更新日志 CHANGELOG.md](CHANGELOG.md)

---

## 1. 系统要求

**Windows 桌面版**

- Windows 10 / 11（x64）；**Python 3.10+**（仅使用标准库，无需 pip 安装依赖；安装 Python 时请勾选
  *Add python.exe to PATH*）
- 至少一个可用的代理出口：自建 VPS 节点、机场订阅中的 hysteria2 / shadowsocks，或本机已在运行的代理客户端
- 内核：完整安装包已内置 sing-box；精简包不包含内核，由 `setup.py` 自动从 GitHub 下载
  （国内网络建议先准备可用的代理，或手动将内核放入 `bin\`）

**Docker 版**

- 可运行 Docker 的 Linux / NAS / Docker Desktop；**无需安装 Python**，镜像已内置内核（构建细节见第 3 节）

## 2. 快速开始

将程序解压至**任意目录**（建议路径不含中文与空格，例如 `D:\AmaneProxy`），然后执行：

```
双击 install.cmd          # 一键完成：初始化文件 + 安装开机自启 + 立即启动
```

面板地址：**http://127.0.0.1:18111**；托盘图标位于任务栏右下角（Windows 11 可能被收进 `^` 溢出区）。

若不使用一键脚本，可手动执行以下三步：

```powershell
python setup.py --root "D:\AmaneProxy"                    # ① 初始化（缺少内核时会自动下载）
powershell -File "D:\AmaneProxy\install-autostart.ps1"    # ② 可选：安装开机自启与守护任务
wscript "D:\AmaneProxy\start.vbs"                         # ③ 启动（无窗口）
```

> 脚本内所有路径均**相对于脚本自身**，整个目录可以自由移动或改名；移动后重新执行一次
> `install-autostart.ps1` 即可修正自启快捷方式。

## 3. Docker 部署（可选）

若不便安装 Python，或需要在 NAS / Linux 服务器上运行，可采用 Docker 部署：镜像内置 sing-box 内核，
配置、规则与日志统一存放于数据卷中，升级镜像不会丢失。

```bash
# 方式一：Compose（推荐）
docker compose up -d
docker compose logs -f

# 方式二：docker run
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

### 3.1 与 Windows 版的差异

| | Windows 版 | Docker 版 |
|---|---|---|
| 内核 | `bin\sing-box.exe`（随包提供 / 由 `setup.py` 下载） | `/usr/local/bin/sing-box`（构建镜像时获取） |
| 配置 / 规则 / 日志 | 程序目录 | `/data`（**必须挂载数据卷**，否则重建容器后配置丢失） |
| 监听地址 | `127.0.0.1` | `0.0.0.0` + 端口映射（默认仅映射至宿主机 `127.0.0.1`，不向外暴露） |
| 托盘图标 | 支持 | 不支持（容器无桌面环境；`AMANEPROXY_TRAY=0`，面板中该项亦显示为关闭） |
| Amane API 地址 | `127.0.0.1:18100` | `host.docker.internal:18100` |

### 3.2 环境变量

环境变量**优先于** `amaneproxy.json`，且不会被写回配置文件，因此同一镜像无需修改配置即可运行。

| 变量 | 镜像默认值 | 说明 |
|---|---|---|
| `AMANEPROXY_HOME` | `/data` | 数据目录（配置 / 规则 / 日志 / pid） |
| `AMANEPROXY_SINGBOX` | `/usr/local/bin/sing-box` | 内核路径 |
| `AMANEPROXY_PROXY_PORT` | `18110` | 代理入口端口 |
| `AMANEPROXY_PANEL_PORT` | `18111` | 面板端口 |
| `AMANEPROXY_CLASH_PORT` | `18112` | 内核 clash API（内部热切换用） |
| `AMANEPROXY_LISTEN_HOST` | `0.0.0.0` | 代理入口监听地址（容器内需为 `0.0.0.0` 才能被映射出去） |
| `AMANEPROXY_PANEL_HOST` | `0.0.0.0` | 面板监听地址 |
| `AMANEPROXY_AMANE_URL` | `http://host.docker.internal:18100` | 宿主机上 Amane 的 API 地址 |
| `AMANEPROXY_AMANE_TOKEN` | 空 | 直接传入 Amane 的 token（可免去挂载文件） |
| `AMANEPROXY_AMANE_TOKEN_FILE` | 空 | token 文件路径，如 `/data/amane-token` |
| `AMANEPROXY_TRAY` | `0` | 容器内关闭托盘 |
| `AMANEPROXY_DEFAULT_OUTBOUND` | 空 | 默认出口：`jp` / `kr` / `us` / `auto` / `direct` |
| `TZ` | `UTC` | 日志时间区，如 `Asia/Shanghai` |

### 3.3 使 Amane 使用容器内的调度器

1. 在**宿主机**的 Amane 中将 `network.proxy` 设为 `http://127.0.0.1:18110`
   （容器已将 18110 映射至宿主机回环地址，**不应填写容器名或容器 IP**）。
   在面板中点击「让 Amane 走本调度器」写入的也是该值，对宿主机而言正确。
2. 面板的「Amane 集成」需读取宿主机 Amane 的 token，二选一：
   - **挂载 token 文件**（compose 中附有注释示例）：
     `- C:/Users/你的用户名/AppData/Local/Amane/token:/data/amane-token:ro`
     （Linux 宿主机为 `~/.local/share/Amane/token`；容器内也识别 `/data/amane-token`）
   - **或通过环境变量传入**：`-e AMANEPROXY_AMANE_TOKEN=<token 内容>`
3. 若 Amane 报网络超时，可将其 `network.timeout` 调大（例如 30 秒）；经代理转发时首包延迟较高。

> **Linux 宿主机亦可使用 host 网络**：compose 中设置 `network_mode: host`，容器与宿主机共用网络栈。
> 此时 `AMANEPROXY_LISTEN_HOST` / `AMANEPROXY_PANEL_HOST` 保持 `127.0.0.1`，
> `AMANEPROXY_AMANE_URL` 可直接使用 `http://127.0.0.1:18100`。host 模式下 `ports:` 不生效。

### 3.4 构建镜像

镜像构建**不依赖 apt**：python 官方 slim 镜像已自带 ca-certificates 与 zoneinfo，内核由镜像内的
python 获取（`docker/get-kernel.py`）；Dockerfile 亦未写 `# syntax=` 指令，以免 BuildKit 先行拉取
Docker Hub 上的 frontend 镜像。因此国内构建只需满足两点：**可拉取 python 基础镜像** 与 **可获取内核包**。

```bash
# 常规构建（GitHub 直连可用时）
docker build -t amaneproxy .
```

国内网络的推荐做法（已在 Ubuntu 22.04 + Docker 20.10 上验证）：

```bash
docker build \
  --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim \
  --build-arg SINGBOX_URL='https://gh-proxy.com/https://github.com/SagerNet/sing-box/releases/download/v1.14.2/sing-box-1.14.2-linux-amd64.tar.gz' \
  -t amaneproxy .
# 实测 35 秒（30MB 内核走加速站 4 秒），镜像 209MB，内核 sing-box 1.14.2
```

下不动 GitHub 时的三条退路（按推荐顺序）：

1. **预先下载内核包并放入 `docker/` 目录**，构建时直接使用，**无需联网**（实测构建耗时 11 秒）：
   ```bash
   # 文件名不限，只要形如 sing-box*.tar.gz；也可直接放入二进制并命名为 docker/sing-box
   # 获取方式（浏览器或任意可访问 GitHub 的主机均可）：
   #   https://gh-proxy.com/https://github.com/SagerNet/sing-box/releases/download/v1.14.2/sing-box-1.14.2-linux-amd64.tar.gz
   docker/sing-box-1.14.2-linux-amd64.tar.gz
   docker build -t amaneproxy .
   ```
2. **为下载指定加速前缀**：`--build-arg SINGBOX_URL='https://gh-proxy.com/https://github.com/...'`
   （实测可用；`ghfast.top` 实测速率仅数 KB/s，不建议使用。）
3. **经由代理下载**：`--build-arg HTTP_PROXY=http://<代理地址>:<端口>`
   （`get-kernel.py` 使用 urllib 下载，会自动读取该变量。）

其它构建参数：

```bash
docker build --build-arg PYTHON_IMAGE=<镜像站>/library/python:3.12-slim -t amaneproxy .  # 更换基础镜像源
docker build --build-arg SINGBOX_VERSION=1.14.2 -t amaneproxy .                          # 固定内核版本
```

多架构（amd64 / arm64）镜像由 GitHub Actions 自动构建并推送至 `ghcr.io/maxuanp/amaneproxy`
（见 `.github/workflows/docker-publish.yml`，其中还包含一项「实际启动容器并访问面板 API」的冒烟测试），
因此也可直接运行：

```bash
docker run -d --name amaneproxy --restart unless-stopped \
  -p 127.0.0.1:18110:18110 -p 127.0.0.1:18111:18111 \
  --add-host host.docker.internal:host-gateway \
  -v amaneproxy-data:/data ghcr.io/maxuanp/amaneproxy:latest
```

### 3.5 排错

```bash
docker compose logs -f                                            # 管理器日志（容器以 --verbose 运行）
docker compose exec amaneproxy tail -f /data/logs/sing-box.log     # 内核日志
docker compose exec amaneproxy cat /data/amaneproxy.json           # 当前设置
docker compose exec amaneproxy python /app/amaneproxy.py --status  # 命令行查看状态
```

- **所有出口均显示「不可用」**：多为出口信息填写有误（服务器 / 端口 / 密码 / SNI），或本机未运行相应的
  代理客户端；请查看 `/data/logs/sing-box.log`。首次运行使用默认模板（指向 `127.0.0.1:1080` 的示例出口）时，
  内核可正常启动，仅探测不到出口 IP，属正常现象。
- **`/data` 为空 / 配置丢失**：数据卷未正确挂载。
- **面板无法打开**：确认 `ports:` 映射的是面板端口，且 `AMANEPROXY_PANEL_HOST=0.0.0.0`。
- **`docker stop` 是否会残留进程**：不会。管理器收到 SIGTERM 后会先停止内核再退出
  （实测耗时 1 秒、退出码 0，日志中包含「sing-box 已停止 / 管理器退出」）。

## 4. 配置代理出口

启动后打开面板 → **总览 → 出口管理**：

| 类型 | 需要的字段 | 说明 |
|---|---|---|
| `hysteria2` | 服务器、端口、SNI、密码 | 机场订阅或自建的 hysteria2 节点。SNI 为服务端证书使用的域名；自签证书请勾选「跳过证书」 |
| `shadowsocks` | 服务器、端口、加密方式、密码 | 常规 SS 节点（sing-box 不支持 SSR 的 `auth_chain_a` 等私有协议，此类协议仅能通过本机客户端接入） |
| `socks` | 服务器、端口 | 指向**本机已运行的代理客户端**（例：Clash / v2rayN / SSR 客户端的 socks5 端口 1080） |

要点：

- 每个出口具有 `cc`（国家代码：`jp` / `kr` / `us` …）。**分流规则按国家代码匹配出口**，
  因此若需「日本站走日本出口」，必须存在 `cc = jp` 的出口；若缺少对应出口，相关域名将自动直连。
- 同一 `cc` 可配置多个出口（例如日本同时存在新 hysteria2 节点与旧客户端），**排序在前的为默认**；
  如需更换主出口，可调整顺序或在面板中手动切换。
- 面板「总览」中可查看每个出口实测的出口 IP / 国家 / 延迟；「默认出口」下拉框决定未命中规则的域名走向
  （可设为 `自动`（在可用出口中选最快）或 `直连`）。

## 5. 将 Amane 接入本调度器

面板 → **Amane 集成** → 点击「让 Amane 走本调度器」。该操作会修改 Amane 的 `network.proxy`，
并记录修改前的值，可随时还原。

> 此处必须使用 `http://127.0.0.1:18110`，**不可使用 `socks5://`**：
> SOCKS5 模式下客户端会先在本地解析域名再交由代理，按域名分流将失效（DNS 被污染时获取的 IP 亦无效）；
> HTTP CONNECT 则会将域名原样传递。

## 6. 面板说明

- **总览**：默认出口 / 故障自动转移开关 / 系统托盘图标开关 / 各出口实测状态 / 出口管理 / 自动转移记录
- **分流规则**：一键预设（日本站点、欧美站点）、按域名后缀 / 完整域名 / 关键字 / 正则新增规则、分流自检
- **域名同步**：定时从 Amane 源配置与站点跳转中获取最新域名并补充规则；出口实测调优开关
- **Amane 集成**：接入 / 还原 / 自定义 `network.proxy`
- **日志**：调度器日志与内核日志

## 7. 托盘图标

管理器以**无窗口**方式常驻运行，系统托盘是其唯一常驻入口：

| 图标 | 含义 |
|---|---|
| 蓝（双向箭头） | 内核运行中，分流生效 |
| 灰 | 已停止 |
| 红 | 启动失败（悬停提示中附有原因） |

- 左键单击 / 双击：打开面板；右键：菜单（打开面板 / 打开 Amane 网页 / 重启内核 / 重载规则并重启 /
  立即同步域名 / 测试三个出口 / 打开日志文件夹 / 退出）
- 悬停显示当前状态与默认出口
- 如需关闭：在面板「总览」中取消勾选「系统托盘图标」，或启动时附加 `--no-tray`
- **Windows 11**：新图标默认被收入任务栏右下角的 `^` 溢出区，可在
  `设置 → 个性化 → 任务栏 → 其他系统托盘图标 → AmaneProxy` 中开启常显

## 8. 常用命令

```powershell
wscript start.vbs                        # 启动（无窗口）
powershell -File status.ps1              # 查看状态（出口 IP / 国家 / 延迟）
powershell -File stop.ps1                # 停止（管理器 + 内核）
powershell -File ensure.ps1              # 未运行时自动拉起
powershell -File install-autostart.ps1   # 安装开机自启与每 5 分钟守护任务
powershell -File uninstall-autostart.ps1 # 取消开机自启
python amaneproxy.py --status            # 命令行查看状态
python amaneproxy.py --no-tray           # 不启用托盘图标
python amaneproxy.py --verbose           # 前台运行并输出日志（排查用）
```

## 9. 端口

| 用途 | 端口 |
|---|---|
| 代理入口（socks5 + http 混合，给 Amane 用） | 127.0.0.1:18110 |
| 本地面板 | 127.0.0.1:18111 |
| 内核 clash API（内部热切换用） | 127.0.0.1:18112 |
| 每个出口的探测入口 | 18211、18212…（按出口顺序往后排） |

上述端口均可在面板中修改（`panel_port` / `proxy_port` / `clash_port`），也可通过环境变量覆盖
（`AMANEPROXY_PROXY_PORT` / `AMANEPROXY_PANEL_PORT` / `AMANEPROXY_CLASH_PORT`）。
桌面版**仅监听 `127.0.0.1`，不对外暴露**；Docker 版默认亦仅将端口映射至宿主机 `127.0.0.1`。

### 更新到新版本

```powershell
# Windows：解压新版并覆盖原目录即可（servers.json / amaneproxy.json / rules.json / logs 不会被覆盖），
# 随后执行 powershell -File install-autostart.ps1 修正自启快捷方式
```

```bash
# Docker：更新镜像后重启，数据均保存在数据卷中
docker compose pull && docker compose up -d
# 或 docker build -t amaneproxy . && docker compose up -d --force-recreate
```

版本历史见 [CHANGELOG.md](CHANGELOG.md)，新版本在 [Releases](https://github.com/maxuanp/AmaneProxy/releases) 发布。

## 10. 常见问题

- **面板无法打开**：执行 `powershell -File status.ps1` 确认进程是否在运行；日志见 `logs\amaneproxy.log`。
- **托盘图标为红色**：内核未成功启动。多为出口信息填写有误（服务器 / 密码 / SNI），或端口被其它程序占用；
  请查阅面板日志中 sing-box 的报错，也可执行 `python amaneproxy.py --verbose` 前台运行以排查。
- **某个出口显示不可用**：请先确认节点自身可用；若日本节点在本机为 SSR 协议，请以 `socks` 类型指向客户端的端口。
- **`setup.py` 下载内核失败**：手动下载 sing-box 的 `windows-amd64` 压缩包，
  将 `sing-box.exe`、`libcronet.dll`、`LICENSE` 放入 `bin\`，然后重新运行 `install.cmd`。
- **Amane 报网络错误**：Amane 自身具有网络超时（默认 10 秒），经代理转发时首包延迟较高；
  若频繁超时，可将 Amane 的 `network.timeout` 调大（例如 30）。

**Docker 相关**

- **`docker build` 卡在拉取基础镜像**：更换镜像站，
  例如 `--build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim`。
- **`docker build` 卡在下载内核**（日志停在 `>>> 下载内核: ...`）：为下载指定加速前缀，
  `--build-arg SINGBOX_URL='https://gh-proxy.com/https://github.com/SagerNet/sing-box/releases/download/v1.14.2/sing-box-1.14.2-linux-amd64.tar.gz'`；
  或先手动下载内核包并放入 `docker/` 目录，即**完全离线构建**（实测耗时 11 秒）。
- **容器内的 `127.0.0.1` 并非宿主机**：接入宿主 Amane 需使用 `AMANEPROXY_AMANE_URL=http://host.docker.internal:18100`；
  反之，Amane 的 `network.proxy` 仍应填写 `http://127.0.0.1:18110`（该端口已映射至宿主机回环地址）。
- **面板无法从其它机器访问**：默认仅绑定宿主机 `127.0.0.1`。可将 compose 中的端口映射改为 `18111:18111`，
  或使用 SSH 隧道（面板无鉴权，请勿直接暴露至公网）。

## 11. 文件清单

```
AmaneProxy\
  amaneproxy.py           管理器本体：生成 sing-box 配置 / 进程守护 / 探测 / 故障转移 / 托盘 / 面板 / Amane 集成
  panel.html              面板 UI
  setup.py                初始化：复制文件 / 下载内核 / 生成 servers.json
  Dockerfile              Docker 镜像（多阶段：获取 Linux 内核 + Python 运行时）
  docker-compose.yml      Compose 编排（端口 / 数据卷 / 环境变量均在此修改）
  docker/get-kernel.py    构建期获取内核（不依赖 apt / curl，仅使用镜像内 python；支持加速前缀与预置包）
  docker/entrypoint.sh    容器入口（准备数据目录 + 接入提示）
  .github/workflows/docker-publish.yml   推送 main / tag 时自动构建 amd64+arm64 镜像至 ghcr.io，并执行容器冒烟测试
  CHANGELOG.md            更新日志
  install.cmd             一键安装（初始化 + 开机自启 + 启动）
  start.vbs               无窗口启动
  ensure.ps1              守护脚本：未运行时拉起（配计划任务，每 5 分钟）
  status.ps1 / stop.ps1   查看状态 / 停止
  install-autostart.ps1 / uninstall-autostart.ps1   安装 / 卸载开机自启
  bin\sing-box.exe        内核（官方 release，GPL-3.0，许可见 bin\LICENSE）
  bin\libcronet.dll       内核自带依赖
  bin\tray_on/off/err.ico 托盘图标
  —— 以下文件于首次运行时自动生成，不属于发布包 ——
  servers.json            出口定义（**明文保存密码**，请勿外传）
  rules.json              分流规则
  amaneproxy.json         设置
  config.json             生成的 sing-box 配置
  logs\                   日志（包含访问过的域名，请勿外传）
```

## 12. 隐私与安全

- 所有服务默认仅监听 `127.0.0.1`，不对外提供端口（Docker 版默认亦仅将端口映射至宿主机回环地址）；
- 面板**无鉴权机制**，请勿直接暴露至公网；如需远程访问，请使用 SSH 隧道；
- `servers.json` 以**明文**保存节点密码（与多数代理客户端一致），`logs\` 会记录访问过的域名。
  在分享安装目录（或 Docker 数据卷）前，请删除 `servers.json`、`amaneproxy.json`、`config.json`、`logs\`；
- 内核 sing-box 由 [SagerNet](https://github.com/SagerNet/sing-box) 提供（GPL-3.0），许可见其自身的 LICENSE；
  本程序自身采用 **MIT** 许可。

## 13. 声明与 AI 参与说明

**AI 参与情况**

- 本项目由**作者与 AI 协作**完成：需求定义、方案取舍、测试与发布由作者负责；代码与文档的相当一部分内容
  由 AI 辅助生成或修改。
- 使用的模型：DeepSeek 系列。早期版本由 “DeepSeek4.1 flash” 辅助生成；v1.4.0 的 Docker 支持与本文档
  的本次修订由 AI 助手（Chatbox + DeepSeek）完成。
- v1.4.0 的发布基于真实环境验证：Ubuntu 22.04 + Docker 20.10（经典 builder），依次验证构建镜像、
  启动容器、面板 API、宿主机经端口映射通过代理返回 200、健康检查 healthy、`docker stop` 正常退出，
  内核版本 sing-box 1.14.2。
- AI 生成的内容**不保证完全无误**，不应视为经过安全审计的软件；投入使用前请自行核查配置
  （出口凭据、监听地址、面板暴露范围）。
- AI 参与**不影响许可**：本程序采用 MIT 许可（见 `LICENSE`）；内置或下载的 sing-box 内核仍为 GPL-3.0。

**免责声明**

- 本程序仅为**本地代理调度器**，不提供任何节点、订阅或加速服务；能否访问特定站点取决于使用者自身的出口。
- 请遵守所在地区的法律法规及目标站点的服务条款；使用本程序所产生的一切后果由使用者自行承担。
- 日志会记录访问过的域名，请妥善保管安装目录 / 数据卷。

---
本程序由 DeepSeek 系列模型辅助生成与维护（详见上文「AI 参与说明」）。
