# T-O09 前端修复

见 /workspace/team/reports/T-F22a.md。结论：T-O09 main 失败的根因是评审 B1（mocks/licence.ts 被旧 .gitignore `licence.*` 忽略，干净检出缺文件）。前端改名为 licenceStore.ts 并加守卫测试，提交 527b65e；另 39c6d80 修复契约升 v0.2.7 后的版本用例。干净检出 CI 步骤全部通过。
