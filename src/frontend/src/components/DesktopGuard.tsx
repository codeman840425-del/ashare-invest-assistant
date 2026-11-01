import { useState, type ReactNode } from 'react';
import { MIN_WIDTH, RECOMMENDED, useViewport } from './viewport';

/** 窗口宽度 < 1280 时整屏遮罩；低于推荐 1440×900 时顶部给可关闭提示 */
export function DesktopGuard({ children }: { children: ReactNode }) {
  const { width, height, kind } = useViewport();
  const [hintClosed, setHintClosed] = useState(false);
  return (
    <>
      {kind === 'below_recommended' && !hintClosed ? (
        <div className="viewport-hint" role="status" data-testid="viewport-hint">
          当前窗口 {width}×{height}，低于推荐的 {RECOMMENDED.width}×{RECOMMENDED.height}，部分面板可能拥挤。
          <a className="close" onClick={() => setHintClosed(true)} style={{ float: 'right' }}>知道了</a>
        </div>
      ) : null}
      {children}
      {kind === 'blocked' ? (
        <div className="desktop-guard" role="alertdialog" aria-modal="true" aria-label="分辨率不足" data-testid="desktop-guard">
          <div>
            <h2>请使用电脑端（宽度 ≥ {MIN_WIDTH}）</h2>
            <div className="muted">当前窗口宽度 {width}px。本工具仅支持桌面浏览器，推荐 {RECOMMENDED.width}×{RECOMMENDED.height} 及以上。</div>
          </div>
        </div>
      ) : null}
    </>
  );
}
