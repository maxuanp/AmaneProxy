# 更新日志

## v1.4.0 — 加 Docker 支持

**新增**

- **Docker 部署**：`Dockerfile`（多阶段构建，镜像里自带 sing-box Linux 内核）、`docker-compose.yml`、
  `docker/entrypoint.sh`。面板端口、代理入口、数据卷、环境变量都配好了，`docker compose up -d` 即用。
- **镜像构建对国内友好**：全程**不依赖 `apt-get`**（python 官方 slim 镜像本来就带 ca-certificates 和
  zoneinfo），也不是 `curl`，取内核用 `docker/get-kernel.py`（只用镜像里现成的 python）。支持：
  - `--build-arg SINGBOX_URL='https://gh-proxy.com/https://github.com/...'` 走加速前缀（实测最快）；
  - `--build-arg HTTP_PROXY=http://...` 构建期走代理；
  - 把 `sing-box-*-linux-*.tar.gz`（或二进制）放进 `docker/` 目录 → **完全离线构建**；
  - `--build-arg PYTHON_IMAGE=<镜像站>/library/python:3.12-slim` 换基础镜像源。
  另外故意**没写** `# syntax=docker/dockerfile:1`，免得 BuildKit 先去 Docker Hub 拉 frontend 镜像。
- **GitHub Actions**（`.github/workflows/docker-publish.yml`）：推 `main` 或打 `v*` tag 时构建
  `linux/amd64 + linux/arm64` 镜像推到 `ghcr.io/maxuanp/amaneproxy`；打 tag 时自动创建 Release；
  另有一个冒烟任务会**真把容器起起来**、请求面板 `/api/state`、跑一次内核 `version`。

**管理器（`amaneproxy.py`）跨平台改造**

- 代码目录 / 数据目录分离：`AMANEPROXY_HOME` 指向数据目录（容器里 `/data`），配置、规则、日志、pid 都写那儿。
- 内核路径自动探测：`AMANEPROXY_SINGBOX` → `bin/sing-box(.exe)` → `PATH`。
- 新增设置项 `listen_host`（代理入口监听地址）、`panel_host`（面板监听地址）、`amane_url`、`amane_token_file`。
- 新增一批环境变量覆盖设置：`AMANEPROXY_PROXY_PORT` / `PANEL_PORT` / `CLASH_PORT` / `LISTEN_HOST` /
  `PANEL_HOST` / `AMANE_URL` / `AMANE_TOKEN` / `AMANE_TOKEN_FILE` / `DEFAULT_OUTBOUND` / `TRAY`。
  环境变量优先于 JSON，而且**不会被写回** `amaneproxy.json`。
- POSIX 上改用 `pid_alive` / `pid_is_amaneproxy` / `kill_pid` 管理进程（不再依赖 `tasklist` / `taskkill`），
  容器重启后 `/data` 里的旧 pid 文件不会误判成「已在运行」。
- Amane 集成在容器里也能用：`amane_url` 可指向 `host.docker.internal:18100`，token 支持环境变量
  `AMANEPROXY_AMANE_TOKEN` 或把 token 文件挂进数据目录（`/data/amane-token`）。
- 首次运行会自动创建数据目录，数据目录不存在也不会报错。

**修复**

- `python amaneproxy.py --status` 在**另一个进程**里执行时永远报 `running: false`（它只看自己进程里的
  内核句柄）。现在会回退去问面板 `/api/state`，容器里 `docker exec amaneproxy python /app/amaneproxy.py --status`
  能拿到真实状态。
- `AMANEPROXY_TRAY=0` 之前只影响实际行为、不写进设置，面板里的「系统托盘图标」会显示成开着；现在会一并同步。

**其它**

- `setup.py` 支持 Linux：自动下载 `linux-amd64/arm64` 内核（tar.gz），不再复制 Windows 专用脚本，
  默认安装目录变成 `~/.local/share/AmaneProxy`。
- README 增加 Docker 章节（构建 / 环境变量 / 接入 Amane / 排错 / 与 Windows 版差异）。
- `.gitattributes` 强制 shell 与代码文件用 LF（避免容器里 `entrypoint.sh` 因 CRLF 报 exec format error）。

**实测环境**：Ubuntu 22.04 + Docker 20.10（经典 builder），构建 35 秒（走加速前缀）/ 11 秒（离线内核包），
镜像 209MB，内核 sing-box 1.14.2；宿主经 `18110` 端口映射走代理返回 200，健康检查 healthy，
`docker stop` 1 秒且退出码 0，空卷首启自动生成模板并可从面板加出口。

## v1.3.0 及更早

早期改动见 [提交记录](https://github.com/maxuanp/AmaneProxy/commits/main)。
