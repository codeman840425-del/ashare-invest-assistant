import { render, screen } from '@testing-library/react';
import { expectTypeOf } from 'vitest';
import type { FactorsResponse } from '../api/marketTypes';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { apiFetch } from '../test/apiFetch';
import { FactorsTab } from './stock/StockTabs';

it('因子集版本只接受真实字符串或 null', () => {
  expectTypeOf<FactorsResponse['factor_set_version']>().toEqualTypeOf<string | null>();
});

it.each([
  ['ETF', '510300.SH', 'not_applicable', '不适用'],
  ['指数', '000300.SH', 'no_source', '暂无因子数据'],
])('%s 无真实因子集：响应 null，页面保留空态并隐藏版本', async (_kind, code, reason, empty) => {
  const response = await apiFetch(`/api/v1/securities/${code}/factors`);
  expect(response.status).toBe(200);
  const data: FactorsResponse = await response.json();
  expect(data.factor_set_version).toBeNull();
  expect(data.items).toEqual([]);
  expect(data.counts).toEqual({ total: 0, by_category: {} });
  expect(data.data_status).toBe('unavailable');
  expect(data.gaps).toEqual(expect.arrayContaining([expect.objectContaining({ reason })]));
  render(<AppProviders client={makeQueryClient(true)}><FactorsTab code={code} /></AppProviders>);
  expect(await screen.findByTestId('factor-empty')).toHaveTextContent(empty);
  expect(screen.getByTestId('tab-factors')).not.toHaveTextContent('因子集');
  expect(screen.getByTestId('tab-factors')).not.toHaveTextContent('mr-factors-85');
});

it('正常股票保留因子数据与已有字符串版本展示', async () => {
  render(<AppProviders client={makeQueryClient(true)}><FactorsTab code="600519.SH" /></AppProviders>);
  expect(await screen.findByText(/因子集 mr-factors-85（示例）/)).toBeInTheDocument();
  expect(screen.getByRole('table')).toBeInTheDocument();
  expect(screen.queryByTestId('factor-empty')).toBeNull();
});
