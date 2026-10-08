# 更新日志

## 未发布（v1.4.0 之后）

**修复**

- **出口实测调优不生效**：调优结果会改写规则的出口，但此前只有在规则条数变化时才重建内核配置，
  于是出现「面板显示已改走 US、实际流量仍走原出口」。现在调优有变化也会一并重载内核。
- **内核启动失败时写接口误报失败**：规则 / 出口 / 设置都是「先落盘、后重启」，内核起不来时
  `start_singbox()` 抛错会冒泡成 HTTP 500，前端提示「保存失败」且不刷新状态（其实已写入文件）。
  现改为返回成功，失败原因经响应里的 `warning` 与面板的 `state.error` 透出。
- **规则表并发竞态**：面板编辑与后台域名同步会同时读写规则表，新增 `rules_lock`；
  「查重 + 插入」在同一次持锁内完成，`save_rules()` 先拷贝再落盘，避免与并发 append 抢迭代器。
- **SOCKS 握手读取不严谨**：`s.recv(s.recv(1)[0])` 在连接提前关闭时会抛 `IndexError`，且不保证读满；
  新增 `_recv_exact()` 按长度读满，出口探测、域名连通性检查与分流自检统一改用。
- **分流自检泄漏 socket**：`selftest()` 异常路径不关闭连接，改用 `try/finally`。
- **Windows 进程判定误判**：`pid_alive()` 原来用 `str(pid) in tasklist 输出` 做子串匹配
  （pid=12 会命中 1234），改按 `tasklist /FO CSV` 的列精确比对；`kill_pid()` 返回 `taskkill` 的真实
  退出码，`--stop` 据此输出，不再谎报「已停止」。
- **shadowsocks 加密方式为空**：面板留空时 `method` 会写成空串导致内核起不来，改为回退 `"none"`。

**新增**

- 面板「出口管理」与「新增出口」支持填写**加密方式**（shadowsocks 的 `method`），留空表示不改动。
- 新增 `.gitignore`：排除 `servers.json`（**明文保存节点密码**）、`logs/`（记录访问域名）、
  `config.json`、`rules.json`、`*.pid`、`data/` 等运行期文件，避免被误提交。

**改进**

- **面板轮询开销**：内核版本改为只查一次并缓存；Amane 可达性与 `network.proxy` 加 5 秒 TTL 缓存；
  selector 查询按国家去重。此前每次 `/api/state`（面板每 5 秒一次）都会起一个子进程并请求一次外网。
- `/api/settings` 增加类型校验（端口 / 间隔必须可转 `int`，否则忽略该键），
  布尔项支持 `"false"` / `"0"` / `"off"` 等字符串写法。
- 出口编辑改为「改副本 + 整表替换」，避免与内核重建并发时读到半更新的出口记录。
- 移除从未被使用的设置项 `probe_url` / `probe_url_fallback`，以及只写不读的 `countries` 属性。
- 前端 `esc()` 补上单引号转义，`rep.error`、面板入口端口等插值一并转义。
- `.gitattributes` 补充 `.gitignore` / `.dockerignore` 的 LF 规则，消除换行符转换告警。

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
  默认安装目录变成 `%LOCALAPPDATA%\AmaneProxy` / `~/.local/share/AmaneProxy`（可用 `--root` 指定别处），
  也不再硬编码开发者的盘符路径；nekoray profiles 只探标准位置。
- README 改版：顶部加入「两种部署方式」对照表、目录与「适用场景」；全文措辞改为正式表述；
  新增 **「声明与 AI 参与说明」**（使用的模型、AI 参与范围、验证方式、免责声明）。
- 隐私与安全一节改为运行时注意事项（监听地址、面板鉴权、明文密码与日志、许可说明）。
- 许可口径澄清：本程序是 **MIT**（见 `LICENSE`），内置 / 下载的 sing-box 内核是 GPL-3.0；
  Dockerfile 的 `org.opencontainers.image.licenses` 标签同步改成 MIT。
- 发布前做了一次隐私扫描（工作区文件 + 全部 git 历史，查 IP / token / 密码 / 私钥 / 个人路径 / 邮箱）：
  仓库里没有节点信息、凭据、日志，也没有开发者的个人路径；并单独体检了 `panel.html`
  （无外部资源引用、无个人 / 无关内容）。
- `.gitattributes` 强制 shell 与代码文件用 LF（避免容器里 `entrypoint.sh` 因 CRLF 报 exec format error）。
- CI：action 升到当前最新大版本（`actions/checkout@v7` / `docker/setup-qemu-action@v4` /
  `docker/setup-buildx-action@v4` / `docker/login-action@v4` / `docker/metadata-action@v6` /
  `docker/build-push-action@v7` / `softprops/action-gh-release@v3`），避免 Node 20 运行时弃用告警。

**实测环境**：Ubuntu 22.04 + Docker 20.10（经典 builder），构建 35 秒（走加速前缀）/ 11 秒（离线内核包），
镜像 209MB，内核 sing-box 1.14.2；宿主经 `18110` 端口映射走代理返回 200，健康检查 healthy，
`docker stop` 1 秒且退出码 0，空卷首启自动生成模板并可从面板加出口。

## v1.3.0 及更早

早期改动见 [提交记录](https://github.com/maxuanp/AmaneProxy/commits/main)。
