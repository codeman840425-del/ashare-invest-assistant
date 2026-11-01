-- 首次初始化数据目录时执行（/docker-entrypoint-initdb.d）。
-- 镜像自带脚本已在 POSTGRES_DB 中创建扩展；这里幂等地再确认一次，并让 template1 也带上扩展，
-- 使之后 CREATE DATABASE（例如测试库）默认启用 TimescaleDB。
CREATE EXTENSION IF NOT EXISTS timescaledb;
\c template1
CREATE EXTENSION IF NOT EXISTS timescaledb;
