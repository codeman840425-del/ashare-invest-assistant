import { useEffect, useState } from 'react';

/** 桌面端最低分辨率（plan：仅支持桌面浏览器，最小 1280 宽，推荐 1440×900） */
export const MIN_WIDTH = 1280;
export const RECOMMENDED = { width: 1440, height: 900 } as const;

export type ViewportClass = 'blocked' | 'below_recommended' | 'ok';

export function classifyViewport(width: number, height: number): ViewportClass {
  if (width < MIN_WIDTH) return 'blocked';
  if (width < RECOMMENDED.width || height < RECOMMENDED.height) return 'below_recommended';
  return 'ok';
}

const read = () => ({ width: window.innerWidth, height: window.innerHeight });

export function useViewport() {
  const [size, setSize] = useState(read);
  useEffect(() => {
    const onResize = () => setSize(read());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return { ...size, kind: classifyViewport(size.width, size.height) };
}
