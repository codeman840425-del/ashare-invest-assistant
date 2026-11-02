/** 评审 8249d6e m2 / m3：mock 注册判定顺序与契约 §7.1 对齐（模式 → IP 限速 → 400 → 409 → 待审核数上限 503 → 蜜罐） */
import { MOCK_INVITE_CODES, MOCK_REGISTER_IP_PER_HOUR, setRegistrationMode, state } from '../mocks/session';

const PW = 'x'.repeat(12) + '1';
const post = (body: unknown) => fetch('/api/v1/auth/register', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
const base = (username: string) => ({ username, password: PW, display_name: '示例', invite_code: MOCK_INVITE_CODES[0], apply_note: '示例：自用研究' });
const code = async (r: Response) => ((await r.json()) as { error?: { code: string; details: unknown } }).error;

describe('m2：IP 限速', () => {
  it('蜜罐命中也计数：5 次命中后第 6 次 → 429 + Retry-After', async () => {
    for (let i = 0; i < MOCK_REGISTER_IP_PER_HOUR; i += 1) {
      const r = await post({ ...base(`demo_hp_${i}`), website: '示例' });
      expect(r.status).toBe(201);
    }
    expect(state.honeypotHits).toHaveLength(MOCK_REGISTER_IP_PER_HOUR);
    const r = await post(base('demo_after'));
    expect(r.status).toBe(429);
    expect(Number(r.headers.get('Retry-After'))).toBeGreaterThan(0);
    expect((await code(r))?.code).toBe('RATE_LIMITED');
    expect(state.users.some((u) => u.username === 'demo_after')).toBe(false);
  });
  it('校验失败也计数；限速先于字段校验', async () => {
    for (let i = 0; i < MOCK_REGISTER_IP_PER_HOUR; i += 1) expect((await post({ ...base('ab'), password: 'x' })).status).toBe(400);
    expect((await post({ ...base('ab'), password: 'x' })).status).toBe(429);
  });
  it('关闭注册先于限速：不计数', async () => {
    setRegistrationMode('closed');
    for (let i = 0; i < MOCK_REGISTER_IP_PER_HOUR + 2; i += 1) expect((await post(base(`demo_c_${i}`))).status).toBe(503);
    expect(state.registerHits).toHaveLength(0);
  });
});

describe('m2：待审核数上限', () => {
  it('pending 数达到上限 → 503 REGISTRATION_CLOSED（与关闭注册同码），先于蜜罐、晚于 409', async () => {
    const pending = state.users.filter((u) => u.status === 'pending').length;
    state.pendingCap = pending;
    const closed = await post(base('demo_cap'));
    expect(closed.status).toBe(503);
    expect((await code(closed))?.code).toBe('REGISTRATION_CLOSED');
    const hp = await post({ ...base('demo_cap_hp'), website: '示例' });
    expect(hp.status).toBe(503);
    expect(state.honeypotHits).toHaveLength(0);
    const taken = state.users[0].username;
    expect((await post(base(taken))).status).toBe(409);
    state.pendingCap = pending + 1;
    expect((await post(base('demo_cap_ok'))).status).toBe(201);
  });
});

describe('m3：website 类型', () => {
  it('非字符串 → 400 website invalid；null 视为未填', async () => {
    const r = await post({ ...base('demo_ws_num'), website: 1 });
    expect(r.status).toBe(400);
    expect(JSON.stringify((await code(r))?.details)).toContain('website');
    expect((await post({ ...base('demo_ws_null'), website: null })).status).toBe(201);
    expect(state.users.some((u) => u.username === 'demo_ws_null')).toBe(true);
    expect(state.honeypotHits).toHaveLength(0);
  });
  it('字符串不校验内容与长度：去空白后非空即命中', async () => {
    expect((await post({ ...base('demo_ws_long'), website: '示'.repeat(300) })).status).toBe(201);
    expect((await post({ ...base('demo_ws_blank'), website: '   ' })).status).toBe(201);
    expect(state.honeypotHits).toEqual(['website']);
    expect(state.users.some((u) => u.username === 'demo_ws_blank')).toBe(true);
  });
});
