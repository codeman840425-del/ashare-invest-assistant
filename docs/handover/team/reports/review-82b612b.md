# 评审 82b612b（T-B48 p11：保存 factor/history 完整序列样例）

- 评审人：项目架构师；时间：2026-11-01 19:45（America/Denver，UTC-7）

## 结论：可以推送

## 核对
- 改动只有 2 行：`probe(..., sample=f"p11_pit_history_{fid}_600519", n=400)`。`_helpers.probe` → `common.save_sample(name, r, max_rows=400)`。样例里的 URL 用的是 `url_redacted`，写盘前会调 `assert_no_licence` ✓。
- 样例写到 probes/results/，这个目录被 `.gitignore:6` 忽略，不会提交 ✓。
- 泄露扫描：
  - gitleaks 扫 probes 导出目录（包括复制过来的 run-20261101-190106 结果，约 6.4 MB）：no leaks。
  - gitleaks 扫 46538a6..82b612b 的提交历史：no leaks。
  - 结果里所有麦蕊 URL 的证书位置都是 `***`（共 333 条以上）；唯一没有 `***` 的 URL 是 `<url>`（查本机 IP 用的，不带证书）。
- 运行时机：这些样例是将来真实运行时才生成的；本次评审没有做真实运行。

## 问题
- B/M：无。
- m1：400 行样例存的是麦蕊的原始数据。目录已经被忽略，但如果要打包发出去（README §8 那套打包流程），要确认数据许可允许这些样例离开本机。→ 运维/后端知悉即可
