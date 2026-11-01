// vitest 示例（T-T01）。演示：纯函数、DOM + testing-library、fetch mock、深色主题。
// 被测的小函数写在本文件里只为演示；真实组件落地后改为 import '@/...'。
import { screen, within } from '@testing-library/dom';
import { describe, expect, it, vi } from 'vitest';

/** api-contract §1：百分比字段为十进制字符串，"3.20" = 3.20% */
function formatPct(value: string | null): string {
  if (value === null) return '—';
  if (!/^-?\d+(\.\d+)?$/.test(value)) throw new Error(`不是十进制字符串：${value}`);
  const sign = value.startsWith('-') ? '' : '+';
  return `${sign}${value}%`;
}

type DataStatus = 'fresh' | 'stale' | 'pending' | 'partial' | 'unavailable';

function renderDataStatusBadge(status: DataStatus, asOf: string): HTMLElement {
  const el = document.createElement('span');
  el.setAttribute('role', 'status');
  el.dataset.status = status;
  el.textContent = status === 'fresh' ? `数据时间 ${asOf}` : `数据${status === 'stale' ? '已过期' : '不完整'}`;
  document.body.appendChild(el);
  return el;
}

describe('formatPct', () => {
  it.each([
    ['3.20', '+3.20%'],
    ['-1.05', '-1.05%'],
    ['0.00', '+0.00%'],
  ])('%s → %s', (input, expected) => {
    expect(formatPct(input)).toBe(expected);
  });

  it('null 显示破折号', () => {
    expect(formatPct(null)).toBe('—');
  });

  it('拒绝 JSON number 风格的浮点误差值', () => {
    expect(() => formatPct('1e-3')).toThrow();
  });
});

describe('DOM 示例', () => {
  it('data_status 徽标（testing-library 查询 + jest-dom 断言）', () => {
    renderDataStatusBadge('stale', '2026-11-02T10:31:00+08:00');
    const badge = screen.getByRole('status');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute('data-status', 'stale');
    expect(within(document.body).getByText('数据已过期')).toBeVisible();
  });

  it('默认深色主题', () => {
    expect(window.matchMedia('(prefers-color-scheme: dark)').matches).toBe(true);
  });
});

describe('网络隔离', () => {
  it('未 mock 的 fetch 直接失败', async () => {
    await expect(fetch('https://example.invalid/api')).rejects.toThrow('禁止真实网络请求');
  });

  it('显式 mock 后可用', async () => {
    const body = { status: 'ok', db: 'ok', redis: 'ok', ingest: 'ok' };
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify(body)));
    const res = await fetch('/api/v1/health');
    expect(await res.json()).toEqual(body);
  });
});
