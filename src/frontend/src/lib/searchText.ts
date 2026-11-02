import { ApiError } from '../api/client';
import { errorText } from '../api/errorPolicy';

/** T-F26：SecurityHit.quote_missing=true 时的徽标（契约 v0.2.9 内 #33 ②；false、null 都不显示） */
export const QUOTE_MISSING_TEXT = '行情源缺此代码';
export const QUOTE_MISSING_TIP = '你的数据证书对应的行情源代码表里没有这只证券，行情、K 线可能取不到；档案等公开主数据不受影响';

/** 搜索出错时下拉里的提示（契约 §7.3 ⑥：400/401/403/429，网关 414；其余按 errorText 通用规则） */
export function searchErrorText(e: unknown): string {
  if (e instanceof ApiError) {
    // #34：网关 414 的信封按通用错误显示 message；信封不是 JSON（code=HTTP_ERROR）时才用前端兜底文案
    if (e.status === 414 && e.code === 'HTTP_ERROR') return '请求地址过长，请缩短搜索词';
    if (e.code === 'RATE_LIMITED') {
      const s = Number(e.details?.retry_after_s);
      if (Number.isFinite(s) && s > 0) return `搜索过于频繁，请 ${Math.ceil(s)} 秒后再试`;
    }
    if (e.code === 'VALIDATION_ERROR') return `搜索词不符合要求：${e.message}`;
  }
  return errorText(e);
}
