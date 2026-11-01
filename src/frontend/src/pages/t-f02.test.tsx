/** T-F02 / T-F02a / T-F04：认证与开通、用户审核、持仓与对账、导入向导（MSW 示例数据） */
import { Blob as NodeBlob, File as NodeFile } from 'node:buffer';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { mockLoginAs } from '../mocks/session';
import { DILUTED_COST_NOTE } from '../i18n/importLabels';
import { IMPORT_422_TEXT } from '../api/importCodes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));

function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}
// 测试口令由代码生成，不在仓库里出现字面口令；mock 只校验长度 ≥ 10
const PW = 'x'.repeat(12);

async function login(username: string) {
  mockLoginAs(null);
  const router = renderAt('/login?next=%2Fportfolio');
  fireEvent.change(await screen.findByLabelText('用户名'), { target: { value: username } });
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: username === 'wrong' ? 'short' : PW } });
  fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));
  return router;
}

describe('登录与账号状态', () => {
  it('用户名或密码错误 → 中文提示，不跳转', async () => {
    const router = await login('wrong');
    expect(await screen.findByTestId('login-error')).toHaveTextContent('用户名或密码不正确');
    expect(router.state.location.pathname).toBe('/login');
  });
  it('账号临时锁定 → 显示剩余时长', async () => {
    await login('locked_user');
    expect(await screen.findByTestId('login-error')).toHaveTextContent(/临时锁定/);
  });
  it('待审核账号 → /account-status?status=pending', async () => {
    const router = await login('pending_user');
    await waitFor(() => expect(router.state.location.pathname).toBe('/account-status'));
    expect(new URLSearchParams(router.state.location.search).get('status')).toBe('pending');
  });
  it('已开通用户登录 → 回到 next', async () => {
    const router = await login('demo_user');
    await waitFor(() => expect(router.state.location.pathname).toBe('/portfolio'));
  });
  it('没有画像的新用户登录 → 也直接回到 next（v0.2.5 无开通引导）', async () => {
    const router = await login('new_user');
    await waitFor(() => expect(router.state.location.pathname).toBe('/portfolio'));
  });
});

describe('用户审核（管理员）', () => {
  it('驳回必须填理由；填写后状态更新', async () => {
    mockLoginAs('admin');
    renderAt('/admin/users');
    fireEvent.click(await screen.findByTestId('act-rejected-pending_user'));
    const dialog = await screen.findByRole('dialog');
    const ok = within(dialog).getByRole('button', { name: /确认驳回/ });
    expect(ok).toBeDisabled();
    fireEvent.change(within(dialog).getByTestId('admin-reason'), { target: { value: '申请说明不完整（示例）' } });
    expect(ok).toBeEnabled();
    fireEvent.click(ok);
    await waitFor(() => expect(screen.queryByTestId('act-rejected-pending_user')).toBeNull());
  });
  it('普通用户访问 /admin/users → 404', async () => {
    renderAt('/admin/users');
    expect(await screen.findByTestId('not-found')).toBeInTheDocument();
  });
});

describe('持仓与对账', () => {
  it('对账页显示“分红计入摊薄成本”口径说明与差异项', async () => {
    renderAt('/portfolio?tab=reconciliation');
    expect(await screen.findByTestId('diluted-cost-note')).toHaveTextContent(DILUTED_COST_NOTE.slice(0, 20));
    expect(screen.getByTestId('recon-tab')).toBeInTheDocument();
  });
  it('成交页：作废成交带“已作废”标记', async () => {
    renderAt('/portfolio?tab=trades');
    expect(await screen.findByTestId('trades-tab')).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('.row-voided')).not.toBeNull());
    expect(screen.getAllByText('已作废').length).toBeGreaterThan(0);
  });
});

describe('导入向导：上传 → 预览着色 → 确认 422 → 写入 → 撤销', () => {
  // jsdom 的 FormData/File 与 Node fetch（MSW 拦截）不兼容：测试里换成 Node 原生实现，组件代码不变
  beforeEach(async () => {
    const nodeForm = await new Response('a=1', { headers: { 'content-type': 'application/x-www-form-urlencoded' } }).formData();
    vi.stubGlobal('FormData', nodeForm.constructor);
    vi.stubGlobal('File', NodeFile);
    vi.stubGlobal('Blob', NodeBlob);
  });
  afterEach(() => vi.unstubAllGlobals());
  const mkFile = (parts: string[], name: string) => new NodeFile(parts, name, { type: 'text/plain' }) as unknown as File;
  it('完整流程', async () => {
    const router = renderAt('/portfolio/import');
    await screen.findByTestId('import-upload');
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = mkFile(['示例列A\t示例列B\n20261026\t09:35:12\n'], 'trades_20261031.txt');
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByTestId('upload-submit')).toBeEnabled());
    fireEvent.click(screen.getByTestId('upload-submit'));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/portfolio\/import\/.+/));
    await screen.findByTestId('confirm-panel', {}, { timeout: 5000 });

    // 预览行按提示码着色：错误 / 需处理 / 跳过 / 仅提示 四种都出现，并有图例
    const table = screen.getByTestId('rows-table');
    await waitFor(() => expect(table.querySelector('.imp-error')).not.toBeNull());
    for (const cls of ['imp-error', 'imp-action', 'imp-skip', 'imp-info']) expect(table.querySelector(`.${cls}`)).not.toBeNull();
    expect(screen.getByTestId('tone-legend')).toBeInTheDocument();
    expect(screen.getByTestId('needs-action')).toBeInTheDocument();

    // 全部写入 → 有错误行被拒
    fireEvent.click(screen.getByRole('radio', { name: /全部写入/ }));
    fireEvent.click(screen.getByTestId('confirm-import'));
    expect(await screen.findByTestId('confirm-error')).toHaveTextContent(IMPORT_422_TEXT.IMPORT_ROW_ERRORS.slice(0, 6));
    // 只写入有效行 → 需处理警告未确认被拒
    fireEvent.click(screen.getByRole('radio', { name: /只写入有效行/ }));
    fireEvent.click(screen.getByTestId('confirm-import'));
    expect(await screen.findByTestId('confirm-error')).toHaveTextContent(IMPORT_422_TEXT.IMPORT_WARNINGS_UNACKNOWLEDGED.slice(0, 6));
    // 接受默认处理 → 写入成功
    fireEvent.click(screen.getByTestId('ack-warnings'));
    fireEvent.click(screen.getByTestId('confirm-import'));
    expect(await screen.findByTestId('import-done')).toHaveTextContent('已写入');

    // 撤销
    fireEvent.click(screen.getByTestId('revert-batch'));
    fireEvent.click(await screen.findByRole('button', { name: /^撤\s*销$/ }));
    expect(await screen.findByTestId('import-reverted', {}, { timeout: 5000 })).toBeInTheDocument();
  }, 20000);

  it('上传非 .txt/.csv → 422 文件级错误列表，不创建批次', async () => {
    const router = renderAt('/portfolio/import');
    await screen.findByTestId('import-upload');
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [mkFile(['x'], 'a.xlsx')] } });
    await waitFor(() => expect(screen.getByTestId('upload-submit')).toBeEnabled());
    fireEvent.click(screen.getByTestId('upload-submit'));
    expect(await screen.findByTestId('upload-file-errors')).toHaveTextContent('文件类型不支持');
    expect(router.state.location.pathname).toBe('/portfolio/import');
  });
});
