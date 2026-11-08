# T-B61 not_set 一次性裁定
结论：不加 scope_key；保留 UUID 作用域，NULL 表示单一聚合 not_set。
依据：证书表无当前行即 not_set，既有 worker 按 UUID 查询，仓库已有部分索引惯例。
source_licence_id 改可空；非空沿用(master_run_id,source_licence_id,attempt)唯一约束。
新增(master_run_id,attempt) WHERE source_licence_id IS NULL 部分唯一索引。
CHECK 强制 NULL 只能 skipped/attempt=1/error_code=licence_unavailable。
本次存在至少一位无当前证书用户即建一条聚合行，不记用户信息；与 active 证书可同时存在，无用户不造批次。
先持父运行锁，重复/并发插入由唯一性兜底；无伪造UUID、无用户归属映射。
直接 skipped，datasets=[]；无意图、无apply、无重试，beat仅扫requested/fetched。
管理端不产生master.*差异告警，不在licences[]塞伪证书；批次解释为“未设置证书，已跳过”。
若需网页批次摘要，位置/接口待后端确认，不扩用现有告警键。
验收：两位无证书＋一位active，重复/并发请求只一NULL skipped和一active requested，仅active有意图。
负例：第二NULL同attempt唯一冲突；NULL requested或attempt=2 CHECK拒绝。
推进重试/beat过deadline，NULL仍skipped，无apply/差异/新master.*告警；元数据无用户信息/证书哨兵。
完整裁定在 docs/plan.md §4.6.5A 第2/4/8/10条；T-B65 接线见紧接子节。
后端须修b4539c2；36e3d76仅修manual截止，不解决空作用域或并发采集。
