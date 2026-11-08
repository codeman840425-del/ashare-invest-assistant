# T-O23 测试 runner 镜像，不是生产栈。只提供 /usr/bin/git 只读包装。
# 构建时安装 git；测试运行时 network none，不再安装依赖。
FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
COPY git-ro.sh /usr/bin/git
RUN chmod 755 /usr/bin/git
