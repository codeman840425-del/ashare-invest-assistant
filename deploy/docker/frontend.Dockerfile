# syntax=docker/dockerfile:1.7
# 前端生产镜像（T-O19）。构建上下文必须是 src/frontend：只 COPY 下面列出的文件，
# 不把 .env、密钥目录或仓库其余部分送进构建。镜像里没有运行时密钥。
# 最终 FROM 与原先 compose 的网关镜像同一 digest。nginx.conf / limits 仍由 compose 只读挂载，不烘焙进镜像。

FROM node:22-bookworm-slim@sha256:aaa4b5baf1ecff3b283486bb1f90405cdda225a3e6f79660d2c559fa510a7292 AS build
WORKDIR /src
ENV CI=true
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN corepack install && pnpm install --frozen-lockfile
COPY index.html vite.config.ts ./
COPY tsconfig.json tsconfig.app.json tsconfig.node.json tsconfig.test.json ./
COPY public ./public
COPY src ./src
RUN pnpm run build

FROM nginx:1.31.2-alpine3.23@sha256:54f2a904c251d5a34adf545a72d32515a15e08418dae0266e23be2e18c66fefa
COPY --from=build /src/dist /usr/share/nginx/html
