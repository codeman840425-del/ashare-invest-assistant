/** T-F24 邀请码注册页（T-B03c 接口；契约 v0.2.8 #11 蜜罐字段 website / form_started_at） */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { calibratedServerNowMs, clockOffsetFromDate, isServerClockCalibrated, noteServerDate, resetServerClock, serverNowMs } from '../lib/serverClock';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { MOCK_INVITE_CODES, mockLoginAs, setRegistrationMode, state } from '../mocks/session';

const PW = 'x'.repeat(12) + '1';
const CODE = MOCK_INVITE_CODES[0];

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

/** 记录发往 /auth/register 的请求体 */
function captureRegister() {
  const bodies: Record<string, unknown>[] = [];
  server.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && request.url.endsWith('/auth/register')) bodies.push((await request.clone().json()) as Record<string, unknown>);
  });
  return bodies;
}

function fillBasics(username: string) {
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: username } });
  fireEvent.change(screen.getByLabelText('显示名'), { target: { value: '示例申请人' } });
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: PW } });
  fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: PW } });
}
const submit = () => fireEvent.click(screen.getByRole('button', { name: /提交注册申请/ }));

const post = (body: Record<string, unknown>) =>
  fetch('/api/v1/auth/register', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
const base = (username: string) => ({ username, password: PW, display_name: '示例', invite_code: CODE, apply_note: '示例：自用研究' });

beforeEach(() => {
  mockLoginAs(null);
  setRegistrationMode('invite');
  resetServerClock();
});
afterEach(() => {
  server.events.removeAllListeners();
  vi.useRealTimers();
});

describe('邀请制注册页：邀请码与申请说明都必填', () => {
  it('两项都不填 → 两条必填提示，不发请求', async () => {
    const bodies = captureRegister();
    renderAt('/register');
    expect(await screen.findByText('注册（邀请制）')).toBeInTheDocument();
    fillBasics('tf24_req');
    submit();
    expect(await screen.findByText('邀请制下必须填写邀请码')).toBeInTheDocument();
    expect(screen.getByText('邀请制下请填写申请说明')).toBeInTheDocument();
    expect(bodies).toHaveLength(0);
  });

  it('只填空白也不行', async () => {
    renderAt('/register');
    await screen.findByTestId('register-page');
    fillBasics('tf24_ws');
    fireEvent.change(screen.getByTestId('reg-invite'), { target: { value: '   ' } });
    fireEvent.change(screen.getByTestId('reg-apply-note'), { target: { value: '  ' } });
    submit();
    expect(await screen.findByText('邀请制下必须填写邀请码')).toBeInTheDocument();
    expect(screen.getByText('邀请制下请填写申请说明')).toBeInTheDocument();
  });

  it('邀请码无效 → 服务端 400 invite_code invalid，显示在邀请码下', async () => {
    renderAt('/register');
    await screen.findByTestId('register-page');
    fillBasics('tf24_bad');
    fireEvent.change(screen.getByTestId('reg-invite'), { target: { value: 'NOT-A-CODE' } });
    fireEvent.change(screen.getByTestId('reg-apply-note'), { target: { value: '示例：自用研究' } });
    submit();
    expect(await screen.findByText('邀请码无效或已失效')).toBeInTheDocument();
  });

  it('open 模式申请说明可选、没有邀请码输入框', async () => {
    setRegistrationMode('open');
    renderAt('/register');
    await screen.findByTestId('register-page');
    expect(screen.queryByTestId('reg-invite')).toBeNull();
    expect(screen.getByText('申请说明（可选）')).toBeInTheDocument();
  });
});

describe('蜜罐字段（v0.2.8 #11）', () => {
  it('website 输入框对用户和读屏器都隐藏：aria-hidden、tabindex=-1、autocomplete=off，不在表单可访问控件里', async () => {
    renderAt('/register');
    await screen.findByTestId('register-page');
    const hp = screen.getByTestId('reg-website') as HTMLInputElement;
    expect(hp.name).toBe('website');
    expect(hp.getAttribute('tabindex')).toBe('-1');
    expect(hp.getAttribute('autocomplete')).toBe('off');
    expect(hp.value).toBe('');
    expect(hp.closest('[aria-hidden="true"]')).not.toBeNull();
    expect(screen.getByTestId('reg-hp')).toHaveClass('reg-hp');
    // 没有关联 label；无障碍树里查不到
    expect(hp.labels?.length ?? 0).toBe(0);
    expect(screen.queryAllByRole('textbox').includes(hp)).toBe(false);
  });

  it('正常提交：website 为空串，form_started_at 为表单打开时的毫秒时间；等待 5 秒后提交 → 真正创建用户', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const bodies = captureRegister();
    const before = Date.now();
    renderAt('/register');
    await screen.findByTestId('register-page');
    const after = Date.now();
    fillBasics('tf24_ok');
    fireEvent.change(screen.getByTestId('reg-invite'), { target: { value: CODE } });
    fireEvent.change(screen.getByTestId('reg-apply-note'), { target: { value: '示例：自用研究' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    submit();
    expect(await screen.findByTestId('register-done')).toBeInTheDocument();
    expect(bodies).toHaveLength(1);
    const b = bodies[0];
    expect(b.website).toBe('');
    expect(Number.isInteger(b.form_started_at)).toBe(true);
    // 按 Date 头校正：Date 只到秒，校正值只会偏早（最多早 1 秒多），不会晚于打开时刻
    expect(b.form_started_at as number).toBeLessThanOrEqual(after);
    expect(b.form_started_at as number).toBeGreaterThan(before - 2000);
    expect(b).toMatchObject({ invite_code: CODE, apply_note: '示例：自用研究' });
    expect(state.users.some((u) => u.username === 'tf24_ok')).toBe(true);
    expect(state.honeypotHits).toEqual([]);
  });

  it('机器人填了 website：照常提交，页面与正常注册一样显示“已提交”，但服务端不建用户', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const bodies = captureRegister();
    renderAt('/register');
    await screen.findByTestId('register-page');
    fillBasics('tf24_bot');
    fireEvent.change(screen.getByTestId('reg-invite'), { target: { value: CODE } });
    fireEvent.change(screen.getByTestId('reg-apply-note'), { target: { value: '示例' } });
    fireEvent.change(screen.getByTestId('reg-website'), { target: { value: 'http://spam.invalid' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    submit();
    expect(await screen.findByTestId('register-done')).toBeInTheDocument();
    expect(bodies[0].website).toBe('http://spam.invalid');
    expect(state.users.some((u) => u.username === 'tf24_bot')).toBe(false);
    expect(state.honeypotHits).toEqual(['website']);
  });

  it('打开表单后 3 秒内提交 → 判为太快（同样显示“已提交”，不建用户）', async () => {
    renderAt('/register');
    await screen.findByTestId('register-page');
    fillBasics('tf24_fast');
    fireEvent.change(screen.getByTestId('reg-invite'), { target: { value: CODE } });
    fireEvent.change(screen.getByTestId('reg-apply-note'), { target: { value: '示例' } });
    submit();
    expect(await screen.findByTestId('register-done')).toBeInTheDocument();
    expect(state.users.some((u) => u.username === 'tf24_fast')).toBe(false);
    expect(state.honeypotHits).toEqual(['too_fast']);
  });
});

describe('mock 按契约 v0.2.8 #11 判定（接口层）', () => {
  it('命中时响应键集合与正常注册相同，不建用户', async () => {
    const ok = await post({ ...base('tf24_api_ok'), website: '', form_started_at: Date.now() - 5000 });
    const hit = await post({ ...base('tf24_api_hp'), website: ' x ', form_started_at: Date.now() - 5000 });
    expect(ok.status).toBe(201);
    expect(hit.status).toBe(201);
    const [a, b] = [await ok.json(), await hit.json()];
    expect(Object.keys(b).sort()).toEqual(Object.keys(a).sort());
    expect(b).toMatchObject({ username: 'tf24_api_hp', status: 'pending' });
    expect(state.users.some((u) => u.username === 'tf24_api_ok')).toBe(true);
    expect(state.users.some((u) => u.username === 'tf24_api_hp')).toBe(false);
  });

  it('1 秒前或未来时间 → 命中；不传 → 正常；两字段同时命中记 both', async () => {
    await post({ ...base('tf24_api_1s'), website: '', form_started_at: Date.now() - 1000 });
    await post({ ...base('tf24_api_fut'), website: '', form_started_at: Date.now() + 60_000 });
    await post({ ...base('tf24_api_both'), website: 'x', form_started_at: Date.now() });
    const none = await post(base('tf24_api_none'));
    expect(none.status).toBe(201);
    expect(state.honeypotHits).toEqual(['too_fast', 'too_fast', 'both']);
    expect(state.users.map((u) => u.username)).toContain('tf24_api_none');
    expect(state.users.map((u) => u.username)).not.toContain('tf24_api_1s');
  });

  it('form_started_at 不是整数 → 400；其他未知字段仍 400；agreements 忽略', async () => {
    expect((await post({ ...base('tf24_api_nan'), form_started_at: 'abc' })).status).toBe(400);
    expect((await post({ ...base('tf24_api_flt'), form_started_at: 1.5 })).status).toBe(400);
    expect((await post({ ...base('tf24_api_extra'), nickname: 'x' })).status).toBe(400);
    expect((await post({ ...base('tf24_api_agr'), agreements: ['terms'] })).status).toBe(201);
  });

  it('closed 模式下即使命中蜜罐也返回 503', async () => {
    setRegistrationMode('closed');
    expect((await post({ ...base('tf24_api_cls'), website: 'x' })).status).toBe(503);
  });
});

describe('服务端时钟校正', () => {
  it('Date 头与本地收到时刻的差值；没有 Date 头时返回 null', () => {
    const recv = Date.parse('2026-11-02T02:00:05.400Z');
    expect(clockOffsetFromDate('Mon, 02 Nov 2026 02:00:03 GMT', recv)).toBe(-2400);
    expect(clockOffsetFromDate(null, recv)).toBeNull();
    expect(clockOffsetFromDate('not a date', recv)).toBeNull();
  });

  it('本地时钟快 1 分钟时，serverNowMs 按服务端时钟给出（form_started_at 不会成为未来时间）', () => {
    const serverNow = Date.parse('2026-11-02T02:00:03.000Z');
    vi.useFakeTimers({ now: serverNow + 60_000 + 400 });
    noteServerDate(new Response(null, { headers: { Date: new Date(serverNow).toUTCString() } }));
    expect(serverNowMs()).toBe(serverNow); // 下界：Date 只到秒，丢掉的 400 毫秒按 0 计
    vi.advanceTimersByTime(1000);
    expect(serverNowMs()).toBe(serverNow + 1000);
  });

  it('评审 8249d6e m1：没有有效 Date 头时未校正，calibratedServerNowMs 返回 null；坏 Date 头不算校正', () => {
    expect(isServerClockCalibrated()).toBe(false);
    expect(calibratedServerNowMs()).toBeNull();
    noteServerDate(new Response(null));
    noteServerDate(new Response(null, { headers: { Date: 'not a date' } }));
    expect(calibratedServerNowMs()).toBeNull();
    noteServerDate(new Response(null, { headers: { Date: new Date().toUTCString() } }));
    expect(typeof calibratedServerNowMs()).toBe('number');
  });

  it('评审 8249d6e m1：/meta/registration 缺 Date 头时，提交不带 form_started_at（服务端不做最短填写时间检查），照常建用户', async () => {
    server.use(http.get('/api/v1/meta/registration', () => new HttpResponse(JSON.stringify({ mode: 'invite' }), { headers: { 'content-type': 'application/json' } })));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const bodies = captureRegister();
    renderAt('/register');
    await screen.findByTestId('register-page');
    fillBasics('tf24_nodate');
    fireEvent.change(screen.getByTestId('reg-invite'), { target: { value: CODE } });
    fireEvent.change(screen.getByTestId('reg-apply-note'), { target: { value: '示例：自用研究' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    submit();
    expect(await screen.findByTestId('register-done')).toBeInTheDocument();
    expect(bodies).toHaveLength(1);
    expect('form_started_at' in bodies[0]).toBe(false);
    expect(bodies[0].website).toBe('');
    expect(state.users.some((u) => u.username === 'tf24_nodate')).toBe(true);
    expect(state.honeypotHits).toEqual([]);
  });
});
