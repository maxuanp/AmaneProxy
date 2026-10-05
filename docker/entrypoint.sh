#!/bin/sh
# AmaneProxy · 容器入口
# 准备数据目录 -> 打印接入提示 -> 交给管理器常驻
set -e

: "${AMANEPROXY_HOME:=/data}"
export AMANEPROXY_HOME
mkdir -p "$AMANEPROXY_HOME/logs"

# 内核: 镜像里自带, 没有的话再看环境变量
if [ ! -x "${AMANEPROXY_SINGBOX:-}" ] && [ -x /usr/local/bin/sing-box ]; then
    AMANEPROXY_SINGBOX=/usr/local/bin/sing-box
    export AMANEPROXY_SINGBOX
fi

if [ "${AMANEPROXY_BANNER:-1}" != "0" ]; then
    proxy_port="${AMANEPROXY_PROXY_PORT:-18110}"
    panel_port="${AMANEPROXY_PANEL_PORT:-18111}"
    cat <<EOF

  AmaneProxy (Docker) ------------------------------------------------
   数据目录   : $AMANEPROXY_HOME        (挂个卷才能保住配置/规则/日志)
   代理入口   : 0.0.0.0:${proxy_port}   -> 宿主机 http://127.0.0.1:${proxy_port}
   面板       : http://127.0.0.1:${panel_port}
   Amane API  : ${AMANEPROXY_AMANE_URL:-http://host.docker.internal:18100}
   接入 Amane : 面板 -> Amane 集成 -> 「让 Amane 走本调度器」
                (Amane 的 network.proxy 用 http://127.0.0.1:${proxy_port}, 不要写容器名)
  --------------------------------------------------------------------

EOF
fi

exec python -u /app/amaneproxy.py "$@"
