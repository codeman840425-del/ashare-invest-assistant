import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { classifyViewport, MIN_WIDTH, RECOMMENDED } from './viewport';
import { DesktopGuard } from './DesktopGuard';

function setViewport(width: number, height: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: width });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: height });
}

describe('classifyViewport 最低分辨率判定', () => {
  it('阈值：最小宽 1280，推荐 1440×900', () => {
    expect(MIN_WIDTH).toBe(1280);
    expect(RECOMMENDED).toEqual({ width: 1440, height: 900 });
  });
  it.each([
    [1024, 768, 'blocked'],
    [1279, 1000, 'blocked'],
    [1280, 720, 'below_recommended'],
    [1366, 768, 'below_recommended'],
    [1439, 900, 'below_recommended'],
    [1440, 899, 'below_recommended'],
    [1440, 900, 'ok'],
    [1920, 1080, 'ok'],
  ] as const)('%i×%i → %s', (w, h, kind) => {
    expect(classifyViewport(w, h)).toBe(kind);
  });
});

describe('DesktopGuard', () => {
  it('≥1440×900：不遮罩、不提示', () => {
    setViewport(1440, 900);
    render(<DesktopGuard><div>内容</div></DesktopGuard>);
    expect(screen.getByText('内容')).toBeInTheDocument();
    expect(screen.queryByTestId('desktop-guard')).toBeNull();
    expect(screen.queryByTestId('viewport-hint')).toBeNull();
  });

  it('1366×768：顶部可关闭的推荐分辨率提示', async () => {
    setViewport(1366, 768);
    render(<DesktopGuard><div>内容</div></DesktopGuard>);
    const hint = screen.getByTestId('viewport-hint');
    expect(hint).toHaveTextContent('1366×768');
    expect(hint).toHaveTextContent('1440×900');
    await userEvent.click(screen.getByText('知道了'));
    expect(screen.queryByTestId('viewport-hint')).toBeNull();
  });

  it('宽度 < 1280：整屏遮罩“请使用电脑端”，窗口拉宽后自动解除', () => {
    setViewport(1200, 800);
    render(<DesktopGuard><div>内容</div></DesktopGuard>);
    const guard = screen.getByRole('alertdialog', { name: '分辨率不足' });
    expect(guard).toHaveTextContent('请使用电脑端（宽度 ≥ 1280）');
    expect(guard).toHaveTextContent('1200px');
    act(() => {
      setViewport(1600, 1000);
      window.dispatchEvent(new Event('resize'));
    });
    expect(screen.queryByTestId('desktop-guard')).toBeNull();
  });
});
