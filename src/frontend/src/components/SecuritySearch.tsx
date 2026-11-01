import { useEffect, useState } from 'react';
import { AutoComplete, Input } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router';
import { CODE_RE, useSecuritySearch } from '../api/marketQueries';
import { LISTING_STATUS, MATCH_KIND, SECURITY_RISK_FLAG } from '../i18n/labels';

/**
 * 顶栏证券搜索（契约 v0.2.7 §7.3 /securities/search，最多 20 条，按服务端 match_kind 层级排序，前端不重排）：
 * 选中或回车完整代码 → /stocks/:code。命中曾用名/旧代码/拼音首字母时显示命中原文。
 */
export function SecuritySearch() {
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [q, setQ] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250);
    return () => clearTimeout(t);
  }, [text]);
  const res = useSecuritySearch(q);
  const go = (code: string) => {
    setText('');
    navigate(`/stocks/${code}`);
  };
  const options = (res.data?.items ?? []).map((h) => ({
    value: h.security_code,
    label: (
      <span className="search-opt" data-testid={`search-hit-${h.security_code}`} data-match={h.match_kind}>
        <span className="mono">{h.security_code}</span>
        <span>{h.name}</span>
        {h.risk_flag ? <span className="search-flag">{SECURITY_RISK_FLAG[h.risk_flag]}</span> : null}
        {h.listing_status && h.listing_status !== 'listed' ? <span className="search-flag">{LISTING_STATUS[h.listing_status]}</span> : null}
        {h.matched_text ? <span className="muted">{MATCH_KIND[h.match_kind]}：{h.matched_text}</span> : null}
      </span>
    ),
  }));
  return (
    <AutoComplete
      value={text}
      options={options}
      onChange={setText}
      onSelect={(v: string) => go(v)}
      popupMatchSelectWidth={240}
      style={{ width: 170 }}
      notFoundContent={q && res.isSuccess ? '无匹配证券' : null}
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
