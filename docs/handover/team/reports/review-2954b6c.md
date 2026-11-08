# 评审 2954b6c（.gitleaksignore 豁免 3 个指纹）：可推
- 评审人：项目架构师；2026-11-07 MST（America/Denver）；干净导出 /tmp/rv2，只读，没有推送，没有调用麦蕊。
- 3 条记录 3e5e288:tb46x.py:S5-sh-holder-code:336/353/372，与 gitleaks-3e5e288.md 一致（336 行两处命中指纹相同，所以 4 处命中对应 3 条记录）。
- 取值只有一个，是字母前缀加连续递增数字，属于虚构值，不是真实<account-field>。
- 实测：secret_scan range d5dd1f8..2954b6c 阻断 0、警告 0（gitleaks 二进制已不在本机，按指示改用 secret_scan）。
- m（运维）：指纹里写死了提交哈希。本地 main 如果变基到 d5dd1f8，3e5e288 会换哈希，这 3 条记录随之失效，gitleaks --all 又会命中。用 merge 方式，或变基后按新哈希重登。CI 不跑 gitleaks，所以不影响 CI。
- B/M：无。
