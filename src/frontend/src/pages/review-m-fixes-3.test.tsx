import { describe, expect, it } from 'vitest';
import { isUuid } from '../lib/uuid';
import { ingestAlerts } from '../mocks/ingestAlerts';
import type { AdminIngestStatus } from '../api/adminTypes';

describe('review-787e453 m2 / 7f46681 m3', () => {
  it('evidence id 只有 uuid 才拼链接', () => {
    expect(isUuid('aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee')).toBe(true);
    expect(isUuid('../admin')).toBe(false);
    expect(isUuid('x')).toBe(false);
  });
  it('mock：master.* 在 #31 键之后，同级 errors.* 按码点升序', () => {
    const base = { leader: 'n1', heartbeat: 'ok', queues: [], budget: { per_minute_limit: 0, used_last_minute: 0 }, ip_limit_alerts_24h: 0,
      errors_24h: [{ upstream_code: 'b', count: 99 }, { upstream_code: 'B', count: 99 }], freshness: [], licences: [] } as unknown as Omit<AdminIngestStatus, 'alerts'>;
    const keys = ingestAlerts(base, { 'master.quote_missing': 'warning' }).map((a) => a.key);
    expect(keys).toEqual(['errors.B', 'errors.b', 'master.quote_missing']);
  });
});
