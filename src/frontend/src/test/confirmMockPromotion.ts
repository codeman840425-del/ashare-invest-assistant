/** 只用于 MSW 合成会话测试，不可用于真实门禁或浏览器审批。 */
import { fireEvent, screen, within } from '@testing-library/react';
export async function confirmMockPromotion(kind: 'decision' | 'lifecycle') {
  const modal = await screen.findByRole('dialog');
  expect(within(modal).getByText(kind === 'decision' ? '审核决定 · 本人密码复核' : '晋级 · 本人密码复核')).toBeInTheDocument();
  fireEvent.change(within(modal).getByLabelText(kind === 'decision' ? '审核复核密码' : '晋级复核密码'), { target: { value: 'x'.repeat(10) } });
  fireEvent.click(within(modal).getByRole('button', { name: kind === 'decision' ? '确认批准 G7' : '确认转入模拟中' }));
}
