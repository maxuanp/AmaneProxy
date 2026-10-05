# AmaneProxy · Docker 镜像（Linux 容器里带 sing-box 内核 + 管理器 + 面板）
# ---------------------------------------------------------------------------
# 用法见 README「Docker 部署」一节, 最简:
#   docker build -t amaneproxy .
#   docker run -d --name amaneproxy --restart unless-stopped \
#     -p 127.0.0.1:18110:18110 -p 127.0.0.1:18111:18111 \
#     --add-host host.docker.internal:host-gateway \
#     -v amaneproxy-data:/data amaneproxy
#   面板 http://127.0.0.1:18111
#
# 设计上刻意避开国内容易卡住的两步:
#   1) 不写 `# syntax=docker/dockerfile:1` —— 写了 BuildKit 会先去 Docker Hub 拉 frontend 镜像;
#   2) 全程不用 apt-get —— python 官方 slim 镜像自带 ca-certificates 和 zoneinfo,
#      取内核用镜像里的 python (docker/get-kernel.py), 不装 curl。
#
# 可调参数:
#   --build-arg PYTHON_IMAGE=<镜像站地址>     拉不动 python 官方镜像时换源
#   --build-arg SINGBOX_VERSION=1.14.2       固定内核版本（默认取最新）
#   --build-arg SINGBOX_URL=<直链/加速前缀>   内核下载走加速站, 例:
#       https://gh-proxy.com/https://github.com/SagerNet/sing-box/releases/download/v1.14.2/sing-box-1.14.2-linux-amd64.tar.gz
#   --build-arg HTTP_PROXY=http://...        构建期下载走代理（urllib 会自动使用）
#   把 sing-box-*-linux-<arch>.tar.gz 或 sing-box 二进制放进 docker/ 目录 -> 直接用它，完全不联网
# ---------------------------------------------------------------------------

ARG PYTHON_IMAGE=python:3.12-slim

# ---------------------------------------------------------------- 1) 取内核
FROM ${PYTHON_IMAGE} AS kernel
ARG SINGBOX_VERSION=latest
ARG SINGBOX_URL=
COPY docker/ /tpl/
RUN python /tpl/get-kernel.py
RUN /sing-box version

# ---------------------------------------------------------------- 2) 运行时
FROM ${PYTHON_IMAGE}

LABEL org.opencontainers.image.title="AmaneProxy" \
      org.opencontainers.image.description="按目标网站自动切换出口的本地代理调度器 (给 Amane 用)" \
      org.opencontainers.image.source="https://github.com/maxuanp/AmaneProxy" \
      org.opencontainers.image.licenses="MIT"
# 说明: 本程序是 MIT; 镜像里内置的 sing-box 内核是 GPL-3.0 (其 LICENSE 由内核包自带)

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AMANEPROXY_HOME=/data \
    AMANEPROXY_SINGBOX=/usr/local/bin/sing-box \
    AMANEPROXY_LISTEN_HOST=0.0.0.0 \
    AMANEPROXY_PANEL_HOST=0.0.0.0 \
    AMANEPROXY_TRAY=0 \
    AMANEPROXY_AMANE_URL=http://host.docker.internal:18100

COPY --from=kernel /sing-box /usr/local/bin/sing-box

WORKDIR /app
COPY amaneproxy.py panel.html LICENSE ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
 && chmod +x /usr/local/bin/entrypoint.sh \
 && mkdir -p /data/logs \
 && python -c "import ssl; p=ssl.get_default_verify_paths(); assert p.cafile, '缺 CA 证书'; print('CA 证书:', p.cafile)" \
 && /usr/local/bin/sing-box version

VOLUME ["/data"]
EXPOSE 18110 18111
HEALTHCHECK --interval=30s --timeout=8s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request,sys; p=os.environ.get('AMANEPROXY_PANEL_PORT','18111'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/api/state',timeout=5).status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--verbose"]
