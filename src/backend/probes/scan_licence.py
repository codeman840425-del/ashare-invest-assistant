"""发送结果前的证书泄漏扫描：只输出“命中/未命中”与命中文件的相对路径，绝不打印证书本身。

用法：python scan_licence.py [目录 ...]   （缺省扫描本脚本所在目录；证书从环境变量 MAIRUI_LICENCE 读取）
退出码：0 未命中；1 命中；2 未设置环境变量。
"""
import os
import sys
from pathlib import Path


def main(argv) -> int:
    lic = os.environ.get("MAIRUI_LICENCE", "")
    if not lic:
        print("MAIRUI_LICENCE 未设置，无法扫描")
        return 2
    needles = {lic.encode("utf-8"), lic.encode("utf-16-le")}
    roots = [Path(a) for a in argv] or [Path(__file__).resolve().parent]
    hits = []
    for root in roots:
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for p in files:
            try:
                b = p.read_bytes()
            except OSError:
                continue
            if any(n in b for n in needles):
                hits.append(str(p))
    if hits:
        print("命中（以下文件含证书，禁止发送）：")
        for h in hits:
            print("  " + h)
        return 1
    print("未命中")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main(sys.argv[1:]))
