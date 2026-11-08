-- 收口演练用的确定性合成数据。只在已迁到 0023、尚未执行 0024 的空库上跑。
-- 不包含 0024 才新增的列（action_plans.updated_at / triggered_at、alerts.handled_at）。
-- 没有真实用户、口令或证书。password_hash 是固定占位，不是凭据。
INSERT INTO app.users (id, username, password_hash, role, status)
VALUES (
  '00000000-0000-4000-8000-000000000001',
  'closeout_synth',
  'synthetic-hash-not-a-credential',
  'user',
  'approved'
);
INSERT INTO app.accounts (id, user_id, name)
VALUES (
  '00000000-0000-4000-8000-000000000002',
  '00000000-0000-4000-8000-000000000001',
  'synth'
);
INSERT INTO app.action_plans (id, user_id, security_code, account_id, status, origin)
VALUES (
  '00000000-0000-4000-8000-000000000003',
  '00000000-0000-4000-8000-000000000001',
  '600000.SH',
  '00000000-0000-4000-8000-000000000002',
  'active',
  'manual'
);
INSERT INTO app.alert_rules (id, user_id, origin, type, security_code)
VALUES (
  '00000000-0000-4000-8000-000000000004',
  '00000000-0000-4000-8000-000000000001',
  'user_custom',
  'custom',
  '600000.SH'
);
INSERT INTO app.alerts (id, user_id, rule_id, security_code, severity, status, triggered_at, dedup_key)
VALUES (
  '00000000-0000-4000-8000-000000000005',
  '00000000-0000-4000-8000-000000000001',
  '00000000-0000-4000-8000-000000000004',
  '600000.SH',
  'info',
  'new',
  '2026-11-01T00:00:00Z',
  'closeout-sample'
);
INSERT INTO market.master_runs (trigger, status, stats)
VALUES ('manual', 'ok', '{"n":1,"sample":"closeout"}'::jsonb);
-- 旧通知。0025 拒绝非 0 的无主 signal_events，所以这里不插入 signal_events。
INSERT INTO app.notifications (id, user_id, kind, severity, title, dedup_key, target_type)
VALUES (
  '00000000-0000-4000-8000-000000000006',
  '00000000-0000-4000-8000-000000000001',
  'system',
  'info',
  'closeout-old-notice',
  'closeout-notice',
  'none'
);
