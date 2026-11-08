# T-B81 临时证书文件（SIGKILL 残留）

探针 `src/backend/probes/tb81.py` 只在 `finally` 里删除临时证书文件。进程收到 SIGKILL 时 `finally` 不执行，文件会留下。仓库里原先没有这份手册（`deploy/runbooks` 与 `docs` 下都没有）。本文只规定运行前后的检查，不记录证书内容，也不抄扫描规则原文。

待架构师把计划或 T-A21 里的相关说明链到本文件。不要在文档里粘贴证书。

## 路径

| 对象 | 路径 | 要求 |
|---|---|---|
| 临时证书文件 | `/workspace/team/runtime/mairui-T-B81.tmp` | 仅在探针运行期间存在；普通文件、权限 0600、属主为运行用户 |
| 私有目录 | `/workspace/team/runtime` | 0700，属主为运行用户 |
| 探针进程 umask | `077` | 与探针内 `os.umask(0o077)` 一致 |
| 停止开关（不是证书） | `src/backend/probes/results/STOP` | 存在则探针停止；本手册不删除它 |

结果目录由探针创建：`src/backend/probes/results/run-<时间>-T-B81`。umask 077 下新建目录为 0700。不要把该目录里的文件内容贴到工单或日志。

## 运行前

```bash
umask 077
deploy/scripts/tb81-licence-tmp-guard.sh before
```

- 私有目录不存在时，守卫会以 0700 创建。
- 目录已存在但不是 0700，或属主不是当前用户：退出 2，不改权限、不列出目录内容。
- 该路径已有目录项（普通文件、软链、特殊文件或异主文件）：视为残留。守卫退出 4，不打开、不跟随、不删除。退出 4 表示必须停手。确认范围并处理完，再次 `before` 得到“文件不存在”之后，才可以放入新文件并启动探针。
- 新文件由操作者在目录内创建，权限 0600。不要用 `echo`、`cat` 或把内容写进命令行。

## 运行后

```bash
deploy/scripts/tb81-licence-tmp-guard.sh after
```

探针正常结束时会删除该文件，`temporary_secret_deleted` 应为 true。`after` 必须报告文件不存在。若仍有目录项，守卫退出 4，不打开、不跟随、不删除。不要在残留还在时重跑探针，也不要打开该文件查看。

## 残留怎么处理

守卫不自动清理。不要对这个路径使用 `shred` 或任何会打开它的命令：软链会被跟随，写入会落到链接目标上。

只在下面这条命令恰好打印一行时，才说明目录项是本目录内、不跨设备的普通文件，且属主为当前用户：

```bash
find /workspace/team/runtime -xdev -maxdepth 1 -name 'mairui-T-B81.tmp' -type f -user "$(id -un)" -printf '%i %p\n'
```

`find -type f` 不匹配软链。输出不是恰好一行，或 `ls -ld` 显示为软链、目录、管道、套接字、设备，或属主不是当前用户：不要 `unlink`，不要写入，停下来交给负责人。是恰好一行普通文件时，只 `unlink` 该目录项，然后再跑 `before`。不要把文件内容抄进工单。

## 明确不做的事

- 不把证书打进仓库、镜像、CI 日志或本手册。
- 不修改探针源码来“顺便”改路径；路径以 `probes/tb81.py` 里的 `SECRET` 为准。
- 不删除 `results/STOP`，不用该目录存放别的密钥。
