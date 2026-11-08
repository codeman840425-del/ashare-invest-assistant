import { useEffect, useState } from 'react';
import { AutoComplete, Input } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router';
import { ApiError } from '../api/client';
import { QUOTE_MISSING_TEXT, QUOTE_MISSING_TIP, searchErrorText, splitHighlight } from '../lib/searchText';
import { CODE_RE, SEARCH_Q_MAX, searchQLength, useSecuritySearch } from '../api/marketQueries';
import { LISTING_STATUS, MATCH_KIND, SECURITY_RISK_FLAG, SECURITY_RISK_FLAG_TIP, SECURITY_TYPE } from '../i18n/labels';

/**
 * 顶栏证券搜索（契约 v0.2.8 §7.3 /securities/search，最多 20 条，按服务端 match_kind 层级排序，前端不重排）：
 * 选中或回车完整代码 → /stocks/:code。命中曾用名（含曾用名的拼音首字母，v0.2.9 内 #33 ②）/旧代码/拼音首字母时显示命中原文。
 * v0.2.9 #41：输入防抖 250 ms；429 按 details.retry_after_s 暂停发请求，到点后自动重查当前输入。
 */
export function SecuritySearch() {
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [q, setQ] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250);
    return () => clearTimeout(t);
  }, [text]);
  // v0.2.9 #41：最近一次 429 的冷却（与输入内容无关，冷却期间换词也不发请求），到点由定时器清除
  const [cooldown, setCooldown] = useState<{ errAt: number; s: number } | null>(null);
  const [seenErrAt, setSeenErrAt] = useState(0);
  const res = useSecuritySearch(q, { paused: cooldown !== null });
  const err = res.error;
  const errAt = res.errorUpdatedAt;
  if (errAt !== seenErrAt) {
    // 渲染期间按新错误调整 state（React 推荐写法，不在 effect 里同步 setState）
    setSeenErrAt(errAt);
    const s = err instanceof ApiError && err.code === 'RATE_LIMITED' ? Number(err.details?.retry_after_s) : NaN;
    if (Number.isFinite(s) && s > 0) setCooldown({ errAt, s: Math.ceil(s) });
  }
  useEffect(() => {
    if (!cooldown) return;
    const t = setTimeout(() => setCooldown(null), cooldown.s * 1000);
    return () => clearTimeout(t);
  }, [cooldown]);
  const tooLong = q.length > 0 && searchQLength(q) > SEARCH_Q_MAX;
  const go = (code: string) => {
    setText('');
    navigate(`/stocks/${code}`);
  };
  // T-F33：命中高亮。代码/简称按当前输入 q 高亮（code_*、name_* 命中时子串就在其中）；
  // 拼音首字母/曾用名/旧代码命中（matched_text 非空）在命中原文上高亮。匹配用归一化后的 q，展示保留原输入。
  const hl = (text: string, on: string) => {
    const parts = splitHighlight(text, on);
    return parts ? <mark className="search-hl" data-testid="search-hl">{parts[1]}</mark> : null;
  };
  const options = (res.data?.items ?? []).map((h) => ({
    value: h.security_code,
    label: (
      <span className="search-opt" data-testid={`search-hit-${h.security_code}`} data-match={h.match_kind}>
        <span className="mono">{h.security_code}{hl(h.security_code, q)}</span>
        <span>{h.name}{hl(h.name, q)}</span>
        {/* v0.2.8：默认结果含 ETF（stock > cdr > etf > index），非股票显示类型徽标 */}
        {h.type !== 'stock' ? <span className="search-flag type" data-testid={`search-type-${h.security_code}`}>{SECURITY_TYPE[h.type] ?? h.type}</span> : null}
        {h.risk_flag ? <span className="search-flag" title={SECURITY_RISK_FLAG_TIP[h.risk_flag]} data-testid={`search-risk-${h.security_code}`}>{SECURITY_RISK_FLAG[h.risk_flag] ?? h.risk_flag}</span> : null}
        {h.listing_status && h.listing_status !== 'listed' ? <span className="search-flag">{LISTING_STATUS[h.listing_status] ?? h.listing_status}</span> : null}
        {h.quote_missing === true ? <span className="search-flag" title={QUOTE_MISSING_TIP} data-testid={`search-quote-missing-${h.security_code}`}>{QUOTE_MISSING_TEXT}</span> : null}
        {h.matched_text ? <span className="muted" data-testid={`search-matched-${h.security_code}`}>{MATCH_KIND[h.match_kind] ?? h.match_kind}：{h.matched_text}{hl(h.matched_text, q)}</span> : null}
      </span>
    ),
  }));
  const status = tooLong ? `搜索词最多 ${SEARCH_Q_MAX} 个字符`
    : err ? searchErrorText(err)
    : q && cooldown ? `搜索过于频繁，请 ${cooldown.s} 秒后再试`
    : q && res.isSuccess ? '无匹配证券' : null;
  return (
    <AutoComplete
      value={text}
      options={tooLong ? [] : options}
      onChange={setText}
      onSelect={(v: string) => go(v)}
      popupMatchSelectWidth={260}
      style={{ width: 170 }}
      notFoundContent={status ? <span data-testid="search-status" role={err || cooldown ? 'alert' : undefined}>{status}</span> : null}
    >
      <Input
        size="small"
        prefix={<SearchOutlined />}
        placeholder="代码/简称"
        aria-label="证券搜索"
        onPressEnter={() => {
          const v = text.trim().toUpperCase();
          if (CODE_RE.test(v)) go(v);
          else if (options.length === 1) go(options[0].value);
        }}
      />
    </AutoComplete>
  );
}
