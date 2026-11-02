#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""部署配置的密钥边界检查（T-A07 §5、plan §2.1B，T-O09）。

  1. deploy/compose/、deploy/env/.env.example、deploy/scripts/、.github/ 下的文本里不出现全站麦蕊证书变量名
     （证书改为用户录入、HPKE 加密存库；部署配置不再传它）；
  2. 任何 compose 服务都不使用 env_file（避免 .env 整体注入）；
  3. 证书封装私钥只给 ingest：secret data_licence_seal_private_keys、名字以 _PRIVATE_KEY / _PRIVATE_KEYS
     结尾的环境变量、挂载源含 private_keys 的卷，都只允许出现在 ingest 服务；
  4. 基础 compose 的顶层 secrets 用 file: 定义两把封装密钥，ingest 拿到私钥+公钥，api 拿到公钥；
  5. .env.example 里没有私钥变量（私钥只走 secret 文件）；
  6. 数据库角色分离（T-O10，契约 v0.2.6 验收“api 数据库角色 SELECT ciphertext 被拒”）：基础 compose 里
     api / ingest 的 DATABASE_URL 用户分别是 aia_api / aia_ingest（不是属主），口令只经 ${AIA_DB_*_PASSWORD} 插值；
     db_password_* secret 用 file: 定义、只挂给 db-roles；任何 compose 文件都不得把 api/ingest 改回属主。
     T-O11：db_password_aia_maint（删除用户数据 CLI 角色）只挂给 db-roles 与 maint-cli；maint-cli 没有 DATABASE_URL
     （不回落到属主）；任何服务的 environment 里都没有 AIA_MAINT_DATABASE_URL*（只由入口包装在容器内生成）。
  7. APP_MASTER_KEY 只走 secret 文件（T-O11）：任何服务的 environment 里都没有 APP_MASTER_KEY；基础 compose 顶层
     secret app_master_key 用 file: 定义；.env.example 不得给它赋值。按服务分配用显式白名单 MASTER_KEY_ALLOC
     （plan e56462c）：api / worker 必须挂，表中其余服务不得挂；任何 compose 文件里出现表里没有的服务 → 失败
     （新增服务必须先登记“挂或不挂”）；ingest 必须设 AIA_FORBID_APP_MASTER_KEY: "1" 并用入口包装（发现主密钥即拒绝启动），
     任何 compose 文件都不得改掉。
  8. 不悄悄换主密钥（T-O11 评审 M1）：deploy/scripts/compose.sh 不直接调用 app-master-keygen.sh，只经
     app-master-key-ensure.sh（已有 → 用；旧 .env 有 → 迁移；库有数据 → 拒绝；全新空库 → 生成）；基础 compose 里
     api / worker 设 AIA_REQUIRE_APP_MASTER_KEY: "1"（没挂 secret 就拒绝启动，不回落临时密钥），任何 compose 文件都不得改掉它。

失败退出码 1，依赖缺失退出码 2。用法：check_secret_boundary.py [--repo DIR]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("缺少 pyyaml：uv run --no-project --with pyyaml==6.0.3 python scripts/ci/check_secret_boundary.py", file=sys.stderr)
    sys.exit(2)

COMPOSE_DIR = "deploy/compose"
BASE_COMPOSE = "deploy/compose/docker-compose.yml"
ENV_EXAMPLE = "deploy/env/.env.example"
TEXT_ROOTS = ["deploy/compose", "deploy/env/.env.example", "deploy/scripts", ".github"]
# 拼接避免本文件成为 rg 命中以外的“配置引用”；扫描脚本里保留该名字是为了做比对
FORBIDDEN_NAME = "MAIRUI_" + "LICENCE"
PRIVATE_SECRET = "data_licence_seal_private_keys"
PUBLIC_SECRET = "data_licence_seal_public_keys"
PRIVATE_ENV_RE = re.compile(r"_PRIVATE_KEYS?$")
PRIVATE_OWNER = "ingest"
DB_ROLE_OF = {"api": ("aia_api", "AIA_DB_API_PASSWORD"), "ingest": ("aia_ingest", "AIA_DB_INGEST_PASSWORD"),
              # 冷却记录定时清理（T-B10 部署项）：与 api 同角色调用同一函数，不得用属主
              "cooldown-purge": ("aia_api", "AIA_DB_API_PASSWORD")}
# 不挂任何 secret 的服务（只需 DATABASE_URL）
NO_SECRET_SVCS = ("cooldown-purge",)
DB_PW_SECRETS = ("db_password_aia_api", "db_password_aia_ingest", "db_password_aia_maint")
DB_PW_OWNER = "db-roles"
MAINT_SVC = "maint-cli"
DB_PW_ALLOWED = {s: {DB_PW_OWNER} for s in DB_PW_SECRETS} | {"db_password_aia_maint": {DB_PW_OWNER, MAINT_SVC}}
MAINT_URL_ENV_RE = re.compile(r"^AIA_MAINT_DATABASE_URL")
MASTER_ENV = "APP_MASTER_KEY"
MASTER_SECRET = "app_master_key"
# 显式白名单（plan e56462c“APP_MASTER_KEY 按服务分配”，CI 规则 7）：True = 必须挂 app_master_key，False = 不得挂。
# 新增 compose 服务必须先登记在这里，否则 CI 失败。
MASTER_KEY_ALLOC = {
    "api": True, "worker": True,
    "ingest": False, "beat": False, "signal-rt": False, "maint-cli": False, "migrate": False,
    "timescale-apply": False, "db-roles": False, "cooldown-purge": False,
    "nginx": False, "postgres": False, "redis": False,
}
MASTER_OWNERS = tuple(k for k, v in MASTER_KEY_ALLOC.items() if v)
MASTER_FORBID_ENV = "AIA_FORBID_APP_MASTER_KEY"
MASTER_FORBID_SVCS = ("ingest",)
SECRET_ENV_ENTRY = ["sh", "/aia/secret-env.sh"]
MASTER_REQUIRE_ENV = "AIA_REQUIRE_APP_MASTER_KEY"
COMPOSE_SH = "deploy/scripts/compose.sh"
KEY_ENSURE = "app-master-key-ensure.sh"
KEY_GEN = "app-master-keygen.sh"
DB_URL_RE = re.compile(r"^postgresql(?:\+\w+)?://([^:@/]+):(\$\{(\w+)[^}]*\})@")


def _texts(repo: Path):
    for root in TEXT_ROOTS:
        p = repo / root
        files = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else []
        for f in files:
            try:
                yield f.relative_to(repo).as_posix(), f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue


def _env_keys(env) -> list[str]:
    if isinstance(env, dict):
        return [str(k) for k in env]
    if isinstance(env, list):
        return [str(x).split("=", 1)[0] for x in env]
    return []


def _secret_names(secrets) -> list[str]:
    out = []
    for s in secrets or []:
        out.append(str(s.get("source")) if isinstance(s, dict) else str(s))
    return out


def _volume_sources(vols) -> list[str]:
    out = []
    for v in vols or []:
        out.append(str(v.get("source", "")) if isinstance(v, dict) else str(v).split(":", 1)[0])
    return out


def check(repo: Path) -> list[str]:
    errs: list[str] = []
    for rel, text in _texts(repo):
        for i, line in enumerate(text.splitlines(), 1):
            if FORBIDDEN_NAME in line:
                errs.append(f"{rel}:{i}: 部署配置不得再引用全站麦蕊证书变量（T-O09）")

    compose_files = sorted((repo / COMPOSE_DIR).glob("*.y*ml"))
    if not (repo / BASE_COMPOSE).is_file():
        errs.append(f"{BASE_COMPOSE} 不存在")
    for f in compose_files:
        rel = f.relative_to(repo).as_posix()
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for name, svc in (doc.get("services") or {}).items():
            svc = svc or {}
            where = f"{rel}: 服务 {name}"
            if "env_file" in svc:
                errs.append(f"{where} 使用了 env_file（禁止整体注入 .env）")
            if name == PRIVATE_OWNER:
                continue
            for k in _env_keys(svc.get("environment")):
                if PRIVATE_ENV_RE.search(k):
                    errs.append(f"{where} 的环境变量 {k} 是私钥，只允许 {PRIVATE_OWNER}")
            if PRIVATE_SECRET in _secret_names(svc.get("secrets")):
                errs.append(f"{where} 挂了 {PRIVATE_SECRET}，只允许 {PRIVATE_OWNER}")
            for src in _volume_sources(svc.get("volumes")):
                if "private_keys" in src:
                    errs.append(f"{where} 挂载了私钥路径，只允许 {PRIVATE_OWNER}")
        for name, svc in (doc.get("services") or {}).items():
            svc = svc or {}
            names = set(_secret_names(svc.get("secrets")))
            for sn in sorted(names & set(DB_PW_SECRETS)):
                if name not in DB_PW_ALLOWED[sn]:
                    errs.append(f"{rel}: 服务 {name} 挂了 {sn}，只允许 {'/'.join(sorted(DB_PW_ALLOWED[sn]))}")
            if name not in MASTER_KEY_ALLOC:
                errs.append(f"{rel}: 服务 {name} 未在 MASTER_KEY_ALLOC 白名单登记（新增服务必须先登记是否挂 {MASTER_SECRET}，plan e56462c）")
            if name in MASTER_FORBID_SVCS and MASTER_FORBID_ENV in _env_keys(svc.get("environment")):
                fenv = svc.get("environment")
                fv = fenv.get(MASTER_FORBID_ENV) if isinstance(fenv, dict) else next(
                    (e.split("=", 1)[1] for e in fenv if isinstance(e, str) and e.startswith(MASTER_FORBID_ENV + "=")), None)
                if str(fv) != "1":
                    errs.append(f"{rel}: 服务 {name} 的 {MASTER_FORBID_ENV} 必须是 \"1\"（发现主密钥即拒绝启动）")
            if name in MASTER_FORBID_SVCS and "entrypoint" in svc and svc["entrypoint"] != SECRET_ENV_ENTRY:
                errs.append(f"{rel}: 服务 {name} 的 entrypoint 必须是入口包装 {SECRET_ENV_ENTRY}（主密钥检测）")
            if MASTER_SECRET in names and name not in MASTER_OWNERS:
                errs.append(f"{rel}: 服务 {name} 挂了 {MASTER_SECRET}，只允许 {'/'.join(MASTER_OWNERS)}")
            for k in _env_keys(svc.get("environment")):
                if k == MASTER_ENV:
                    errs.append(f"{rel}: 服务 {name} 的 environment 有 {MASTER_ENV}（只走 secret 文件 {MASTER_SECRET}，T-O11）")
                if MAINT_URL_ENV_RE.match(k):
                    errs.append(f"{rel}: 服务 {name} 的 environment 有 {k}（aia_maint 连接串只由入口包装在容器内生成）")
            env = svc.get("environment")
            if name in MASTER_OWNERS and MASTER_REQUIRE_ENV in _env_keys(env):
                v = env.get(MASTER_REQUIRE_ENV) if isinstance(env, dict) else next(
                    (e.split("=", 1)[1] for e in env if isinstance(e, str) and e.startswith(MASTER_REQUIRE_ENV + "=")), None)
                if str(v) != "1":
                    errs.append(f"{rel}: 服务 {name} 的 {MASTER_REQUIRE_ENV} 必须是 \"1\"（不回落临时主密钥，M1）")
            if name in NO_SECRET_SVCS and svc.get("secrets"):
                errs.append(f"{rel}: 服务 {name} 不得挂任何 secret（只以 aia_api 连库调用清理函数）")
            if name == MAINT_SVC and "DATABASE_URL" in _env_keys(svc.get("environment")):
                errs.append(f"{rel}: 服务 {MAINT_SVC} 不得有 DATABASE_URL（只能以 aia_maint 连接，不回落到属主）")
            env = svc.get("environment")
            url = env.get("DATABASE_URL") if isinstance(env, dict) else next(
                (e.split("=", 1)[1] for e in (env or []) if isinstance(e, str) and e.startswith("DATABASE_URL=")), None)
            if name in DB_ROLE_OF and url is not None:
                user, var = DB_ROLE_OF[name]
                m = DB_URL_RE.match(str(url))
                if not m or m.group(1) != user or m.group(3) != var:
                    errs.append(f"{rel}: 服务 {name} 的 DATABASE_URL 应为 {user}:${{{var}}}@…（不得用属主或明文口令）")
        for sname, sdef in (doc.get("secrets") or {}).items():
            if isinstance(sdef, dict) and "environment" in sdef:
                errs.append(f"{rel}: secret {sname} 用 environment: 定义（必须用 file:，不经环境变量）")

    base = repo / BASE_COMPOSE
    if base.is_file():
        doc = yaml.safe_load(base.read_text(encoding="utf-8")) or {}
        top = doc.get("secrets") or {}
        for s in (PRIVATE_SECRET, PUBLIC_SECRET):
            if not (isinstance(top.get(s), dict) and "file" in top[s]):
                errs.append(f"{BASE_COMPOSE}: 顶层 secrets 缺少 {s}（file:）")
        for s in (*DB_PW_SECRETS, MASTER_SECRET):
            if not (isinstance(top.get(s), dict) and "file" in top[s]):
                errs.append(f"{BASE_COMPOSE}: 顶层 secrets 缺少 {s}（file:）")
        svcs = doc.get("services") or {}
        for svc in DB_ROLE_OF:
            env = (svcs.get(svc) or {}).get("environment")
            if not (isinstance(env, dict) and "DATABASE_URL" in env):
                errs.append(f"{BASE_COMPOSE}: 服务 {svc} 没有显式 DATABASE_URL（必须用独立角色）")
        need = {PRIVATE_OWNER: {PRIVATE_SECRET, PUBLIC_SECRET}, "api": {PUBLIC_SECRET, MASTER_SECRET},
                "worker": {MASTER_SECRET}}
        for svc in MASTER_OWNERS:
            env = (svcs.get(svc) or {}).get("environment")
            if not (isinstance(env, dict) and str(env.get(MASTER_REQUIRE_ENV)) == "1"):
                errs.append(f"{BASE_COMPOSE}: 服务 {svc} 缺少 {MASTER_REQUIRE_ENV}: \"1\"（没挂 app_master_key 要拒绝启动，M1）")
        for svc in MASTER_FORBID_SVCS:
            sd = svcs.get(svc) or {}
            env = sd.get("environment")
            if not (isinstance(env, dict) and str(env.get(MASTER_FORBID_ENV)) == "1"):
                errs.append(f"{BASE_COMPOSE}: 服务 {svc} 缺少 {MASTER_FORBID_ENV}: \"1\"（plan：ingest 不得持有主密钥）")
            if sd.get("entrypoint") != SECRET_ENV_ENTRY:
                errs.append(f"{BASE_COMPOSE}: 服务 {svc} 没用入口包装 {SECRET_ENV_ENTRY}（主密钥检测）")
        for svc, want in need.items():
            have = set(_secret_names((svcs.get(svc) or {}).get("secrets")))
            if not want <= have:
                errs.append(f"{BASE_COMPOSE}: 服务 {svc} 缺少 secrets {sorted(want - have)}")

    csh = repo / COMPOSE_SH
    if csh.is_file():
        code = [ln.split("#", 1)[0] for ln in csh.read_text(encoding="utf-8").splitlines()]
        if any(KEY_GEN in ln for ln in code):
            errs.append(f"{COMPOSE_SH}: 不得直接调用 {KEY_GEN}（会给已有部署悄悄换主密钥），改经 {KEY_ENSURE}（M1）")
        if not any(KEY_ENSURE in ln for ln in code):
            errs.append(f"{COMPOSE_SH}: 没有调用 {KEY_ENSURE}（缺主密钥文件时的迁移 / 拒绝判定，M1）")
    else:
        errs.append(f"{COMPOSE_SH} 不存在")
    if not (repo / "deploy/scripts" / KEY_ENSURE).is_file():
        errs.append(f"deploy/scripts/{KEY_ENSURE} 不存在")

    ex = repo / ENV_EXAMPLE
    if ex.is_file():
        for i, line in enumerate(ex.read_text(encoding="utf-8").splitlines(), 1):
            key = line.split("=", 1)[0].strip()
            if "=" in line and not line.lstrip().startswith("#") and PRIVATE_ENV_RE.search(key):
                errs.append(f"{ENV_EXAMPLE}:{i}: 私钥不得出现在 .env（只走 secret 文件）")
            if "=" in line and not line.lstrip().startswith("#") and key == MASTER_ENV:
                errs.append(f"{ENV_EXAMPLE}:{i}: {MASTER_ENV} 不得出现在 .env（只走 secret 文件 {MASTER_SECRET}，T-O11）")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    errs = check(Path(ap.parse_args().repo))
    for e in errs:
        print(f"::error title=secret-boundary::{e}")
    print("secret-boundary: OK" if not errs else f"secret-boundary: {len(errs)} 处问题")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
