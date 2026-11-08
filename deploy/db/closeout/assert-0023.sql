-- 升到 0024 之前：确认仍是旧结构，并且合成行都在。
DO $$
BEGIN
  IF (SELECT version_num FROM public.alembic_version) IS DISTINCT FROM '0023' THEN
    RAISE EXCEPTION 'closeout: expected alembic 0023 before upgrade';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'app' AND table_name = 'action_plans'
       AND column_name IN ('updated_at', 'triggered_at')
  ) OR EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'app' AND table_name = 'alerts' AND column_name = 'handled_at'
  ) THEN
    RAISE EXCEPTION 'closeout: 0024 columns already present';
  END IF;
  IF (SELECT count(*) FROM app.users) <> 1
     OR (SELECT count(*) FROM app.accounts) <> 1
     OR (SELECT count(*) FROM app.action_plans) <> 1
     OR (SELECT count(*) FROM app.alert_rules) <> 1
     OR (SELECT count(*) FROM app.alerts) <> 1
     OR (SELECT count(*) FROM market.master_runs) <> 1
     OR (SELECT count(*) FROM app.notifications) <> 1
     OR (SELECT count(*) FROM app.signal_events) <> 0 THEN
    RAISE EXCEPTION 'closeout: synthetic row counts';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM app.notifications
     WHERE id = '00000000-0000-4000-8000-000000000006'
       AND title = 'closeout-old-notice' AND dedup_key = 'closeout-notice'
       AND read_at IS NULL
  ) THEN
    RAISE EXCEPTION 'closeout: old notification missing before upgrade';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM app.action_plans
     WHERE id = '00000000-0000-4000-8000-000000000003'
       AND status = 'active' AND security_code = '600000.SH'
       AND account_id = '00000000-0000-4000-8000-000000000002'
       AND user_id = '00000000-0000-4000-8000-000000000001'
  ) THEN
    RAISE EXCEPTION 'closeout: plan row missing before upgrade';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM market.master_runs
     WHERE stats = '{"n":1,"sample":"closeout"}'::jsonb AND status = 'ok' AND trigger = 'manual'
  ) THEN
    RAISE EXCEPTION 'closeout: master_runs sample missing before upgrade';
  END IF;
END $$;
