"""T-T28 固定本机隔离PG身份检查；仅 inspect 元数据，不启动/停止容器或读取环境/口令。"""
import json
import subprocess
from pathlib import Path

PG = '/tb58-isolated-pg3'
SOCKET = '/tmp/tb58-pg3-socket'
VOLUME = 'cb74ac8b598dc70429ffc2081fae178a80cf6cad138e58e9d7cf93d100b1487d'


def verify_isolated_pg() -> None:
    fmt = ('{"name":{{json .Name}},"network":{{json .HostConfig.NetworkMode}},'
           '"ports":{{json .NetworkSettings.Ports}},"mounts":{{json .Mounts}},'
           '"running":{{json .State.Running}}}')
    try:
        ids = subprocess.check_output(['docker', 'ps', '-aq'], text=True).split()
        rows = [json.loads(subprocess.check_output(
            ['docker', 'inspect', '--format', fmt, i], text=True)) for i in ids]
    except Exception:
        raise RuntimeError('无法验证固定隔离容器；禁止连接PG') from None
    pg = next((r for r in rows if r['name'] == PG), None)
    if not pg or not pg['running'] or pg['network'] != 'none' or pg['ports']:
        raise RuntimeError('隔离PG身份/网络不符；禁止连接')
    expected = {(SOCKET, SOCKET), (f'/var/lib/docker/volumes/{VOLUME}/_data', '/var/lib/postgresql/data')}
    if {(m['Source'], m['Destination']) for m in pg['mounts']} != expected:
        raise RuntimeError('隔离PG挂载不符；禁止连接')
    for other in rows:
        if other['name'] == PG:
            continue
        for mine in pg['mounts']:
            for theirs in other['mounts']:
                a, b = Path(mine['Source']), Path(theirs['Source'])
                if a == b or a in b.parents or b in a.parents:
                    raise RuntimeError('隔离PG与其他容器共享挂载；禁止连接')
