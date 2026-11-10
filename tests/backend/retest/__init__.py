"""T-T81：拼接校验独立用例目录（retest_plan §2.7）。

被测实现属 T-B136；未接线前本目录用例挂 ``pending_impl`` marker 整体 skip。
接线后：把 test_splice_validation.py 的 ``SpliceChecker`` 占位类替换为
``from app.retest.splice import SpliceChecker``（模块名以后端落地为准）。
"""
