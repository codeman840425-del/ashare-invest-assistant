-- 升到合并后的真实 head 之后：旧行计数和关键字段还在。
-- 不把 head 写成 0024 或 0026。新列可以出现，但不能改掉旧通知/计划/运行记录。
DO $$
BEGIN
  IF (SELECT count(*) FROM app.action_plans) <> 1
     OR (SELECT count(*) FROM app.alert_rules) <> 1
     OR (SELECT count(*) FROM app.alerts) <> 1
     OR (SELECT count(*) FROM app.notifications) <> 1
     OR (SELECT count(*) FROM market.master_runs) <> 1
     OR (SELECT count(*) FROM app.signal_events) <> 0 THEN
    RAISE EXCEPTION 'closeout: retained counts changed';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM app.notifications
     WHERE id = '00000000-0000-4000-8000-000000000006'
       AND user_id = '00000000-0000-4000-8000-000000000001'
       AND title = 'closeout-old-notice' AND dedup_key = 'closeout-notice'
       AND kind = 'system' AND read_at IS NULL
  ) THEN
    RAISE EXCEPTION 'closeout: old notification not retained';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM app.action_plans
     WHERE id = '00000000-0000-4000-8000-000000000003'
       AND status = 'active' AND security_code = '600000.SH'
       AND account_id = '00000000-0000-4000-8000-000000000002'
  ) THEN
    RAISE EXCEPTION 'closeout: plan row not retained';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM app.alerts
     WHERE id = '00000000-0000-4000-8000-000000000005'
       AND status = 'new' AND dedup_key = 'closeout-sample'
  ) THEN
    RAISE EXCEPTION 'closeout: alert row not retained';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM market.master_runs
     WHERE stats = '{"n":1,"sample":"closeout"}'::jsonb AND status = 'ok' AND trigger = 'manual'
  ) THEN
    RAISE EXCEPTION 'closeout: master_runs sample changed';
  END IF;
END $$;
