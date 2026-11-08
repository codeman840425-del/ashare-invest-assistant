# T-B02a 数据模型第二轮（后端）
- plan §8 T-B02a：三层表、candidate_signals CHECK、不可变触发器、按月分区、部分索引（3A.6）、market_rule_versions、event_definitions
- 附带：config/market_rules.yaml 按 T006b §7 / plan 更新（50 万股上限仅主板+创业板；限价申报仅沪市）；config/ 下所有 yaml（含 llm.yaml）由后端维护，键与默认值以 plan §6.1 为准
- 验收：upgrade/downgrade 往返；TimescaleDB 容器跑通；ruff/mypy 干净
- 之后：T-B03（认证与同意）
