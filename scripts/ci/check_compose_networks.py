#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""compose 网络拆分检查（T-O68 / 契约 §7.11.5 / plan R19 方案 B 的网络层）。

基础文件必须声明四张网：
  default / aia_internal ：internal: true（漏写 networks 的新服务也出不了网）
  aia_egress             ：可出网，仅 EGRESS_ALLOWLIST（ingest + opt-in 的 master-bootstrap）
  aia_edge               ：非 internal，关闭 IP masquerade，只给要向宿主发布端口的服务

每个服务必须用映射式 networks 挂上 aia_internal（compose 合并时才能与覆盖层做键并集，
列表式会整段替换、冲掉内部网）。发布了 ports 的服务必须同时挂非 internal 网（aia_edge，
或已在出网白名单里的 aia_egress），因为只挂 internal 时宿主通常连不上发布端口。

覆盖文件不得削弱顶层网络属性，也不得把未登记服务挂到 aia_egress / aia_edge。
覆盖层顶层 networks 与各服务 networks 都只许使用与基础层相同的四个登记名
（default / aia_internal / aia_egress / aia_edge），禁止另开可出网桥给 worker 等服务。
覆盖层不得对已登记网络设置 name / external / driver（T-A97 N4–N6）；
internal 与 edge 的 IP masquerade 开关仍按下面的削弱检查处理。driver_opts: {} 与基础合并，不拦。
发布了 ports 的服务必须绑定 127.0.0.1，不得 0.0.0.0 或省略宿主地址。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_secret_boundary as ccs  # noqa: E402

COMPOSE_DIR = "deploy/compose"
BASE_COMPOSE = "deploy/compose/docker-compose.yml"

NET_INTERNAL = "aia_internal"
NET_EGRESS = "aia_egress"
NET_EDGE = "aia_edge"
NET_DEFAULT = "default"
REGISTERED_NETWORKS: frozenset[str] = frozenset({NET_DEFAULT, NET_INTERNAL, NET_EGRESS, NET_EDGE})
MASQ_OPT = "com.docker.network.bridge.enable_ip_masquerade"

# 默认可出网的只有 ingest。master-bootstrap 是编排者裁定④ 的 opt-in profile（主数据首导），
# 默认 up 不启动；扩表白名单须再经编排者裁定。
EGRESS_ALLOWLIST: frozenset[str] = frozenset({"ingest", "master-bootstrap"})
# 允许挂 aia_edge 的服务（发布 127.0.0.1 端口，无出网伪装）
EDGE_ALLOWLIST: frozenset[str] = frozenset({"nginx", "postgres", "redis"})
REQUIRED_ON_EDGE: frozenset[str] = frozenset({"nginx"})

PREFIX_RE = "${AIA_VOLUME_PREFIX:?请用 deploy/scripts/compose.sh 调用}"


def _nets(svc: object) -> set[str] | None:
    """返回网络名集合；未写 networks 为 empty set；格式非法返回 None。"""
    if not isinstance(svc, dict):
        return None
    n = svc.get("networks")
    if n is None:
        return set()
    if isinstance(n, dict):
        return {str(k) for k in n}
    return None  # 列表或其他类型一律拒绝


def _has_ports(svc: object) -> bool:
    if not isinstance(svc, dict):
        return False
    p = svc.get("ports")
    return bool(p)


def _port_binds_localhost(entry: object) -> bool:
    """短语法必须以 127.0.0.1: 开头；长语法必须 host_ip: 127.0.0.1。"""
    if isinstance(entry, dict):
        return str(entry.get("host_ip") or "") == "127.0.0.1"
    s = str(entry).strip().strip('"').strip("'")
    return s.startswith("127.0.0.1:")


def _check_ports_localhost(where: str, svc: object, errs: list[str]) -> None:
    if not isinstance(svc, dict):
        return
    for i, entry in enumerate(svc.get("ports") or []):
        if not _port_binds_localhost(entry):
            errs.append(f"{where}: ports[{i}] 必须绑定 127.0.0.1（不得 0.0.0.0 或省略宿主地址）")


def _expect_named(where: str, net: dict[str, Any], suffix: str, errs: list[str]) -> None:
    want = f"{PREFIX_RE}_{suffix}"
    got = net.get("name")
    if got != want:
        errs.append(f"{where}: name 必须是 {want}（发现 {got!r}）")


def _check_base_networks(rel: str, nets: dict[str, Any], errs: list[str]) -> None:
    for key in (NET_DEFAULT, NET_INTERNAL, NET_EGRESS, NET_EDGE):
        if key not in nets:
            errs.append(f"{rel}: 顶层 networks 缺少 {key}")
    extra = set(nets) - {NET_DEFAULT, NET_INTERNAL, NET_EGRESS, NET_EDGE}
    if extra:
        errs.append(f"{rel}: 顶层 networks 有未登记的网络 {sorted(extra)}")

    for key, suffix, must_internal in (
        (NET_DEFAULT, "default", True),
        (NET_INTERNAL, "internal", True),
        (NET_EGRESS, "egress", False),
    ):
        net = nets.get(key)
        if not isinstance(net, dict):
            if key in nets:
                errs.append(f"{rel}: networks.{key} 必须是映射")
            continue
        _expect_named(f"{rel}: networks.{key}", net, suffix, errs)
        internal = bool(net.get("internal"))
        if must_internal and not internal:
            errs.append(f"{rel}: networks.{key} 必须 internal: true（漏写 networks 或内部通信不得出网）")
        if not must_internal and internal:
            errs.append(f"{rel}: networks.{key} 不得 internal: true（ingest 需要出网）")

    edge = nets.get(NET_EDGE)
    if not isinstance(edge, dict):
        return
    _expect_named(f"{rel}: networks.{NET_EDGE}", edge, "edge", errs)
    if edge.get("internal"):
        errs.append(f"{rel}: networks.{NET_EDGE} 不得 internal: true（否则宿主端口发布通常不可达）")
    if edge.get("driver") not in (None, "bridge"):
        errs.append(f"{rel}: networks.{NET_EDGE}.driver 必须是 bridge 或省略（发现 {edge.get('driver')!r}）")
    opts = edge.get("driver_opts") or {}
    if not isinstance(opts, dict) or str(opts.get(MASQ_OPT)).lower() != "false":
        errs.append(
            f"{rel}: networks.{NET_EDGE} 必须设置 driver_opts.{MASQ_OPT}: \"false\"（无出网伪装）"
        )


def _check_overlay_networks(rel: str, nets: dict[str, Any], errs: list[str]) -> None:
    """覆盖层若重定义网络，不得削弱基础约束；不得新声明未登记的网络。

    T-A97 N4–N6：叠加层不得对已登记网络设置 name / external / driver。
    （N4：external: true + name: bridge 会把服务送进有伪装的默认桥；
     N5：改 driver，如 macvlan；N6/M5：把 edge/internal 的 name 改成 egress 的网络名。）
    internal 与 enable_ip_masquerade 已在本函数后续检查，不在这三项里重复定义。
    """
    extra = set(nets) - REGISTERED_NETWORKS
    if extra:
        errs.append(
            f"{rel}: 顶层 networks 有未登记的网络 {sorted(extra)}"
            f"（只许 {sorted(REGISTERED_NETWORKS)}）"
        )
    for key in REGISTERED_NETWORKS:
        net = nets.get(key)
        if not isinstance(net, dict):
            continue
        set_keys = [k for k in ("name", "external", "driver") if k in net]
        if set_keys:
            errs.append(
                f"{rel}: 不得对已登记网络 {key} 设置 {'/'.join(set_keys)}"
                f"（叠加层不得改 name、external、driver；T-A97 N4–N6）"
            )
    for key in (NET_DEFAULT, NET_INTERNAL):
        net = nets.get(key)
        if net is None:
            continue
        if not isinstance(net, dict) or not net.get("internal"):
            errs.append(f"{rel}: 不得把 networks.{key} 改成非 internal")
    egress = nets.get(NET_EGRESS)
    if isinstance(egress, dict) and egress.get("internal"):
        errs.append(f"{rel}: 不得把 networks.{NET_EGRESS} 改成 internal")
    edge = nets.get(NET_EDGE)
    if isinstance(edge, dict):
        if edge.get("internal"):
            errs.append(f"{rel}: 不得把 networks.{NET_EDGE} 改成 internal")
        opts = edge.get("driver_opts") or {}
        if isinstance(opts, dict) and MASQ_OPT in opts and str(opts.get(MASQ_OPT)).lower() != "false":
            errs.append(f"{rel}: 不得打开 networks.{NET_EDGE} 的 IP masquerade")


def _check_service(
    where: str,
    name: str,
    nets: set[str],
    *,
    has_ports: bool,
    require_internal: bool,
    errs: list[str],
) -> None:
    unknown = nets - REGISTERED_NETWORKS
    if unknown:
        errs.append(
            f"{where}: 不得接入未登记网络 {sorted(unknown)}"
            f"（只许 {sorted(REGISTERED_NETWORKS)}）"
        )
    if require_internal and NET_INTERNAL not in nets:
        errs.append(f"{where}: 必须挂 {NET_INTERNAL}（用映射式 networks，以便与覆盖层合并）")
    if NET_EGRESS in nets and name not in EGRESS_ALLOWLIST:
        errs.append(
            f"{where}: 不得接入可出网网络 {NET_EGRESS}（白名单仅 {sorted(EGRESS_ALLOWLIST)}；扩表白名单须经编排者裁定）"
        )
    if name in EGRESS_ALLOWLIST and NET_EGRESS not in nets and require_internal:
        errs.append(f"{where}: 出网白名单服务必须挂 {NET_EGRESS}")
    if NET_EDGE in nets and name not in EDGE_ALLOWLIST:
        errs.append(
            f"{where}: 不得接入 {NET_EDGE}（白名单仅 {sorted(EDGE_ALLOWLIST)}）"
        )
    if name in REQUIRED_ON_EDGE and NET_EDGE not in nets and require_internal:
        errs.append(f"{where}: 必须挂 {NET_EDGE}（向宿主发布 127.0.0.1 端口）")
    if has_ports and NET_EDGE not in nets and NET_EGRESS not in nets:
        errs.append(
            f"{where}: 发布了 ports，必须挂非 internal 网络（{NET_EDGE} 或已在出网白名单的 {NET_EGRESS}），"
            f"否则宿主通常连不上发布端口"
        )


def check(repo: Path) -> list[str]:
    errs: list[str] = []
    files = sorted((repo / COMPOSE_DIR).glob("*.y*ml"))
    if not files:
        errs.append(f"{COMPOSE_DIR} 下没有 compose 文件")
        return errs

    base_path = repo / BASE_COMPOSE
    if not base_path.is_file():
        errs.append(f"缺少 {BASE_COMPOSE}")
        return errs

    # per-file 检查 + 合并后的 ports/networks（覆盖层映射键与基础并集）
    merged_nets: dict[str, set[str]] = {}
    merged_ports: dict[str, bool] = {}
    base_names: set[str] = set()

    for f in files:
        rel = f.relative_to(repo).as_posix()
        doc = ccs._load(f, rel, errs)
        if doc is None:
            continue
        is_base = rel == BASE_COMPOSE
        top = doc.get("networks")
        if is_base:
            if not isinstance(top, dict):
                errs.append(f"{rel}: 必须声明顶层 networks")
            else:
                _check_base_networks(rel, top, errs)
        elif isinstance(top, dict):
            _check_overlay_networks(rel, top, errs)

        services = doc.get("services") or {}
        if not isinstance(services, dict):
            errs.append(f"{rel}: services 必须是映射")
            continue
        for name, svc in services.items():
            where = f"{rel}: 服务 {name}"
            nets = _nets(svc)
            if nets is None:
                errs.append(f"{where}: networks 必须是映射（不能用列表，覆盖层列表会整段替换、冲掉 {NET_INTERNAL}）")
                continue
            ports = _has_ports(svc)
            if ports:
                _check_ports_localhost(where, svc, errs)
            # 基础文件要求每个服务都挂内部网；覆盖层可以只写增量
            _check_service(
                where,
                name,
                nets,
                has_ports=ports if is_base else False,  # 覆盖层 ports 放到合并后再判
                require_internal=is_base,
                errs=errs,
            )
            # 文件按名字排序，覆盖层可能先于基础文件出现，合并只能做并集，不能覆盖。
            if is_base:
                base_names.add(name)
            merged_nets.setdefault(name, set()).update(nets)
            merged_ports[name] = merged_ports.get(name, False) or ports

    # 合并视图：发布端口的服务、白名单、内部网
    for name, nets in merged_nets.items():
        where = f"合并后: 服务 {name}"
        _check_service(
            where,
            name,
            nets,
            has_ports=merged_ports.get(name, False),
            require_internal=name in base_names or True,
            errs=errs,
        )
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    errs = check(Path(ap.parse_args().repo))
    for e in errs:
        print(f"::error title=compose-networks::{e}")
    print("compose-networks: OK" if not errs else f"compose-networks: {len(errs)} 处问题")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
