# review-cc5ea15（T-O18）  结论：可推；M1 连通性留作部署前项
- worker 设了 MASTER_SNAPSHOT_PATH（默认 /var/lib/aia-dev/master）；专用卷 ${AIA_VOLUME_PREFIX}_master 只给 worker、读写；Dockerfile 建好目录（aia:700）。
- DATA_VOLUMES 已登记 master，required={worker}，path_env 对应，测试已补。
- worker 在默认网络上，有出网。但真实 uid 写入、到三家交易所的连通性都未实测（T-O18.md 自认，探测结果 200/500/403）→ M1（运维，部署前在目标机实测）。
