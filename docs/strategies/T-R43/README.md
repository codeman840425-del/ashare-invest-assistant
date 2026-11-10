# T-R43｜按 T-A83 修 G7 核对稿（B-1 + L-1..L-6 + S20 + compliance 引用）

不改 lifecycle、不写批准、用户勾选列保持未勾；夹具数值均【虚构】。

| 项 | 处理 | 位置 |
|---|---|---|
| B-1 H18 | 改回「缺证据」；null 回放脚本写明不读夹具行情、不构成 H18 证据 | `T-R41/g7_review_H-01_S-01.md` H18、H 小结、§5；`T-R42/README.md`；`T-R42/null_propagation_replay.py` docstring |
| L-1 S7 | 卡上新增 C1/C2 正例 S01-FX9、S01-FX10；`s01_fixture_eval.py` 按夹具输入复算 FX1..10 | `cards/st_pullback_ma.md` validation 末尾 |
| L-2 S13 | 更正：S-01 夹具均 main，无科创板夹具；引用改为 FX5/FX6/FX7 | g7_review S13 |
| L-3 | H7 W3 正例改 FX9；H11/S11 data_needs 行号去掉 epistemic 段 | g7_review H7/H11/S11 |
| L-4 | 四个脚本 `--mutate` 改为真实篡改输入，原因与被篡改项对应 | `T-R42/*.py` |
| L-5 | 删 `cost_replay.py` abandon_on_cost 死分支；impact_tiers 与成本放弃阈值登记为 gaps | `T-R42/cost_replay*.{py,json}` |
| L-6 | g7_review §3 去掉仓库外路径 | g7_review §3 |
| ④ S20 | 卡头:6 ③ 注明 v1 选股只扫「持仓 ∪ 自选」；运行侧用例归后端，初核仍缺证据 | `cards/st_pullback_ma.md:6` |
| ④ H16/S16 | 补服务端 lint 引用 reviews.py:317-324、:351/:353 与 test_tb83b_reauth.py:246 | g7_review H16/S16 |

计数：合计 40；一致 32 / 不一致 0 / 缺证据 8（H-01 16/0/4：H4/H12/H17/H18；S-01 16/0/4：S3/S12/S18/S20）。
T-R44 后：一致 33 / 不一致 0 / 缺证据 7（H17 按 T-T46 定点用例改一致；H-01 17/0/3：H4/H12/H18；S-01 不变）。
T-R46 后：一致 34 / 不一致 0 / 缺证据 6（H18 按 T-T48 正式用例、T-A86 裁定改一致，未经 prepare()；H-01 18/0/2：H4/H12；S-01 不变）。
T-R47 后：一致 35 / 不一致 0 / 缺证据 5（S3 按语义审核改一致、待架构师复核；H-01 18/0/2：H4/H12；S-01 17/0/3：S12/S18/S20），以 g7_review §5 为准；步骤 A 不在 40 项内，仍未决。

`s01_fixture_eval.py`：普通与 `-O` 均 exit 0；`--mutate <name>` 真实篡改卡文本/夹具后 exit 1。参考层复算 ≠ T-B71 执行器实跑。
