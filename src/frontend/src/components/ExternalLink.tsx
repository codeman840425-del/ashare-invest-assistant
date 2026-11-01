import type { ReactNode } from 'react';
import { ExportOutlined } from '@ant-design/icons';
import { safeExternalUrl } from '../lib/url';

/**
 * 外部原文链接：新窗口打开、不带 opener 与 referrer。前端只渲染 <a>，从不请求外部地址（公告正文不转存、不抓取）。
 */
export function ExternalLink({ href, children, title }: { href: string | null | undefined; children: ReactNode; title?: string }) {
  const url = safeExternalUrl(href);
  if (!url) return <span className="muted">{children}</span>;
  return (
    <a className="ext-link" href={url} target="_blank" rel="noopener noreferrer nofollow" referrerPolicy="no-referrer" title={title ?? '在新窗口打开原文（外部网站）'}>
      {children}
      <ExportOutlined className="ext-icon" aria-hidden />
    </a>
  );
}
