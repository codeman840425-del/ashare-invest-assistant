import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen } from '@testing-library/react';
import { CardDisclaimer, DISCLAIMER_TEXT, RiskDisclosure } from './RiskDisclosure';

/** 读取 docs/strategies/compliance/disclaimer.md 原文：「## 文案」下第一行引用块（去掉行首 "> "，其余逐字保留） */
function disclaimerFromDoc(): string {
  const md = readFileSync(resolve(__dirname, '../../../../docs/strategies/compliance/disclaimer.md'), 'utf8');
  const sec = md.slice(md.indexOf('## 文案'));
  const line = sec.split('\n').find((l) => l.startsWith('> '));
  if (!line) throw new Error('disclaimer.md 中没有找到文案引用块');
  return line.slice(2).replace(/\r$/, '');
}

describe('RiskDisclosure 固定免责提示（契约 v0.2.5 #1）', () => {
  it('文案与 docs/strategies/compliance/disclaimer.md 原文完全一致（含标点、空格）', () => {
    const doc = disclaimerFromDoc();
    expect(doc.length).toBeGreaterThan(20);
    expect(DISCLAIMER_TEXT).toBe(doc);
  });

  it('页面底部渲染的文字与原文完全一致，并附 Lightweight Charts 署名', () => {
    render(<RiskDisclosure />);
    const el = screen.getByTestId('risk-disclosure');
    expect(el.querySelector('span')!.textContent).toBe(disclaimerFromDoc());
    expect(el).toHaveTextContent('TradingView Lightweight Charts');
  });

  it('可关闭署名，但免责提示仍在', () => {
    render(<RiskDisclosure showAttribution={false} />);
    const el = screen.getByTestId('risk-disclosure');
    expect(el.textContent).toBe(disclaimerFromDoc());
  });

  it('卡片内的免责提示文字与原文完全一致', () => {
    render(<CardDisclaimer />);
    expect(screen.getByTestId('card-disclaimer').textContent).toBe(disclaimerFromDoc());
  });
});
