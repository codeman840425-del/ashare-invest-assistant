# T-O32 收口部署预演：机械盘点（运维，2026-11-08 17:00 北京时间）：没建库，没 merge，没测试
已读 rules/no-idle-2026-11-08.md。origin/main 是 34c88c3（T-O28，用户机已部署到这里）。
合并候选（都是已提交的，精确 hash 和来源）：
- A：ops/T-O31 5ad701081028cd130d6f885b881463e8dc79d755（运维）= T-O29 adf9fb4 → merge 0efb11f（加 T-A30 7f5b061）→ T-O30 3d3612e → T-O31。包含全部 deploy 新改动：T-O29/T-O30 的 grants、T-O31 的 nginx。
- B：共享 main 96a4b683a658bfecb2d2446f2b71120832e5c872（各角色已提交的内容，比 origin 多 27 个提交）。7f5b061 之后多了 a36eb1e、943ae52、c6d4ffa、96a4b68，都是前端/契约/文档，没有 deploy 或迁移改动；迁移 head 仍是 0024。
- git merge-tree main ops/T-O31 显示无冲突（只是试算，没真的 merge）。共享 main 工作区有 30 行别人未提交的改动，不混入。
不是候选（待核实）：test/T-T01 d0a6644 不在 main 里，属于测试分支，要等测试角色或编排者确认；backup/* 分支、test/p2n10a（148fc8e 已在 main 里）都排除。
数据库：
- 盘点下来，没有可用的“带数据 0023 隔离库”。aia-t01-o15 的卷和其他角色的 p2n06-pg 都属于禁止触碰的共享库；T-O27/29/30 的隔离库都是空的，而且已经删掉；用户机上的是真实数据，禁止用。
- 合成数据方案的候选：deploy/db/drill/（sample-schema 和 sample-data 是确定性伪随机数据，但样例表不是真实迁移的结构）、db-restore-drill.sh（临时容器）、app/cli/calendar_seed.py。
- 要覆盖“0023 有数据，再升到 0024 并保留数据”，需要 cloud 设计：在全新隔离库上迁到 0023，用合成数据填充，再升级，并且不能用真实用户数据。
基线包：artifacts/T-O32-baseline.tar.gz（取自 A 5ad7010），sha256 2e1fe6b2de74bca8f047be487cd52760b0f14043a433d90e35784e041808e582，98 个文件。
- 内容：整个 deploy/（compose、env 模板 .env.example、scripts、db/roles、nginx、drill）、migrations、alembic.ini、migration_check.py、calendar_seed.py、两个前端 smoke。文件列表：artifacts/T-O32-filelist.txt。
- 扫描：gitleaks dir 0、secret_scan files 0；包里没有 .env 或密钥文件。
待核实：
1. 收口基线用 A 还是 merge(A,B)；B 只多了前端，如果要预演首页 login 200 用真实前端，就需要 B；
2. “8 服务”是不是 api、worker、ingest、beat、signal-rt、nginx、postgres、redis；
3. 隔离预演在 box 上跑的话，T-O14 里 box 的 Docker bridge 网络是坏的，需要 cloud 设计 network none 或 bwrap 的替代方案；
4. 合成数据的规模和覆盖哪些表。
DeepSeek：未用，原因：本阶段只做机械盘点，没有可公开的框架需求。
