"""后台进程入口（worker / beat / ingest / signal-rt）。

启动命令（容器内，WORKDIR=src/backend）：``python -m app.workers.<名字>``，名字为
``worker``、``beat``、``ingest``、``signal_rt``。
健康检查：``python -m app.workers.healthcheck <名字>``。
目前都是占位实现：常驻、定期打日志、写存活文件、SIGTERM/SIGINT 优雅退出。
"""
