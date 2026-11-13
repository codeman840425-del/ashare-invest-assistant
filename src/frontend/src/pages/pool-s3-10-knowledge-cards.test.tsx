import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { server } from '../mocks/server';
import { StrategyCardsPage } from './strategies/StrategyCardsPage';
import type { StrategyCardSummary } from '../api/strategyCardQueries';

// 合成分页夹具，仅验证接线；不作为真实栈/既有三卡验收证据。
const cards: StrategyCardSummary[] = [1, 2, 3].map((n) => ({
  id: `synthetic-card-${n}`, key: `synthetic_${n}`, name: `合成知识卡${n}`,
  category: '合成研究分类', horizons: ['short'], completeness: 'draft',
  current_version_no: n, source_kind: 'builtin', performance: null,
}));
function openPage() {
  render(<AppProviders client={makeQueryClient(true)}><StrategyCardsPage /></AppProviders>);
}

it('按真实分页协议读取卡片，正文按需请求，缺表现不伪造为0', async () => {
  const seen: (string | null)[] = [];
  server.use(
    http.get('/api/v1/strategy-cards', ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      seen.push(cursor);
      return HttpResponse.json(cursor === null
        ? { items: cards.slice(0, 2), next_cursor: 'synthetic-next' }
        : { items: cards.slice(2), next_cursor: null });
    }),
    http.get('/api/v1/strategy-cards/:id', ({ params }) => HttpResponse.json({
      narrative: `合成研究正文 ${params.id}`, risk_level: 'high',
      gates_missing: ['G2:synthetic_missing'], refs: [{ ref: 'SYN-1', title: '合成出处', url: null }],
    })),
  );
  openPage();
  await screen.findByRole('article', { name: cards[0].name });
  await userEvent.click(screen.getByRole('button', { name: '加载更多' }));
  const last = await screen.findByRole('article', { name: cards[2].name });
  expect(screen.getAllByTestId('strategy-knowledge-card')).toHaveLength(3);
  expect(seen).toEqual([null, 'synthetic-next']);
  expect(last).toHaveTextContent('暂无表现记录');
  expect(last).toHaveTextContent('草稿');
  await userEvent.click(within(last).getByRole('button', { name: '阅读正文' }));
  expect(await within(last).findByText(`合成研究正文 ${cards[2].id}`)).toBeInTheDocument();
  expect(last).toHaveTextContent('G2:synthetic_missing');
  expect(last).toHaveTextContent('合成出处');
  expect(last).toHaveTextContent('高风险');
});

it('真实404类错误显示失败，不伪装成无卡或内置卡片', async () => {
  server.use(http.get('/api/v1/strategy-cards', () => HttpResponse.json({
    error: { code: 'NOT_FOUND', message: '合成卡片路径不可用', details: null, request_id: 'synthetic-request' },
  }, { status: 404 })));
  openPage();
  const error = await screen.findByRole('alert');
  expect(error).toHaveTextContent('策略知识卡加载失败');
  expect(error).toHaveAttribute('data-code', 'NOT_FOUND');
  expect(screen.queryByTestId('strategy-knowledge-card')).not.toBeInTheDocument();
  expect(screen.queryByText('暂无可见的策略知识卡')).not.toBeInTheDocument();
});
