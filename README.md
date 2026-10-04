# AmaneProxy · 本地分流代理调度器

给 [Amane](https://github.com/sqzw-x/amane) 用的**本地代理调度器**：本机跑一个 sing-box 内核，
把 Amane 的 `network.proxy` 指向它，就能做到

- **按目标网站自动走不同出口**：日本站 → 日本出口，欧美站 → 美国出口，韩国站 → 韩国出口，其余走默认出口；
- **出口故障自动转移**：某条出口挂了自动切到健康的，恢复后自动切回；
- **定时同步站点域名**：站点换域名时自动补分流规则，避免流量掉到默认出口；
- **出口实测调优**：某个域名在原出口不通时，实测其它出口并自动改走能通的那个；
- 本地面板 + **系统托盘图标**，日常不用碰命令行。

> 本压缩包**不含任何节点/服务器信息、不含任何使用记录**：`servers.json`、`amaneproxy.json`、
> 分流规则、日志都是首次运行时在本机生成的默认文件，你需要自己填自己的出口。

---

## 1. 系统要求

- Windows 10 / 11（x64）
- **Python 3.10+**（只用标准库，不需要 pip 装任何包）
  - 安装时务必勾选 **Add python.exe to PATH**
- 需要一个可用的代理出口（自己的 VPS 节点 / 机场订阅里的 hysteria2、shadowsocks，或本机已有的代理客户端）
- 完整版压缩包已带 sing-box 内核；精简版没有内核，`setup.py` 会自动去 GitHub 下载（国内网络可能需要先有个能用的代理）

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

## 3. 配置你自己的出口

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

## 4. 把 Amane 接进来

面板 → **Amane 集成** → 点「让 Amane 走本调度器」。它会替你改 Amane 的 `network.proxy`，
并记住改之前的值，随时可以「还原」。

> 注意必须是 `http://127.0.0.1:18110`，**不能用 `socks5://`**：
> 走 SOCKS5 时 client 会先在本地解析域名再交给代理，按域名分流就失效了（DNS 被污染时拿到的 IP 也没用）；
> HTTP CONNECT 会把域名原样带过去。

## 5. 面板说明

- **总览**：默认出口 / 故障自动转移开关 / 系统托盘图标开关 / 各出口实测状态 / 出口管理 / 自动转移记录
- **分流规则**：一键预设（日本站、欧美站）、按域名后缀/完整域名/关键字/正则新增规则、分流自检
- **域名同步**：定时从 Amane 的源配置 + 站点跳转里取最新域名补规则；出口实测调优开关
- **Amane 集成**：接入 / 还原 / 自定义 `network.proxy`
- **日志**：调度器日志 + 内核日志

## 6. 托盘图标

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

## 7. 常用命令

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

## 8. 端口

| 用途 | 端口 |
|---|---|
| 代理入口（socks5 + http 混合，给 Amane 用） | 127.0.0.1:18110 |
| 本地面板 | 127.0.0.1:18111 |
| 内核 clash API（内部热切换用） | 127.0.0.1:18112 |
| 每个出口的探测入口 | 18211、18212…（按出口顺序往后排） |

端口都能在面板里改（`panel_port` / `proxy_port` / `clash_port`）。**只监听 127.0.0.1，不对外暴露。**

## 9. 常见问题

- **面板打不开**：`powershell -File status.ps1` 看有没有在跑；`logs\amaneproxy.log` 有日志。
- **托盘是红色**：内核没起来。多半是出口填错（服务器/密码/SNI），或端口被别的程序占了，
  看面板日志里 sing-box 的报错；也可以 `python amaneproxy.py --verbose` 前台跑一次。
- **某个出口显示不可用**：先确认节点自身能用；日本节点如果在你本机是 SSR 协议，请用 `socks` 类型指向你客户端的端口。
- **`setup.py` 下载内核失败**：手动下载 sing-box 的 `windows-amd64` 压缩包，
  把 `sing-box.exe`、`libcronet.dll`、`LICENSE` 放进 `bin\`，然后重新运行 `install.cmd`。
- **Amane 那边报网络错误**：Amane 自身也有个网络超时（默认 10 秒），走代理的首包可能更慢 ——
  如果经常超时，把 Amane 的 `network.timeout` 调大一些（例如 30）。

## 10. 文件清单

```
AmaneProxy\
  amaneproxy.py           管理器本体：生成 sing-box 配置 / 进程守护 / 探测 / 故障转移 / 托盘 / 面板 / Amane 集成
  panel.html              面板 UI
  setup.py                初始化：复制文件 / 下载内核 / 生成 servers.json
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

## 11. 隐私与安全

- 压缩包里**没有**任何服务器地址、密码、订阅链接、token、日志和使用记录；`servers.json` 等文件是
  首次运行在你本机生成的默认模板。
- 所有服务只监听 `127.0.0.1`，不对外提供端口。
- `servers.json` 是**明文**保存节点密码的（和多数代理客户端一样）；`logs\` 里会记录你访问过的域名。
  分享自己的整份安装目录前，记得删掉 `servers.json`、`amaneproxy.json`、`config.json`、`logs\`。
- 内核 sing-box 由 [SagerNet](https://github.com/SagerNet/sing-box) 提供，GPL-3.0，版权与许可见 `bin\LICENSE`。
