import { useEffect, useState } from 'react';
import { AutoComplete, Input } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router';
import { CODE_RE, useSecuritySearch } from '../api/marketQueries';

/** 顶栏证券搜索（契约 §7.3 /securities?q=，最多 20 条）：选中或回车完整代码 → /stocks/:code */
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
  const options = (res.data ?? []).map((h) => ({
    value: h.security_code,
    label: (
      <span className="search-opt">
        <span className="mono">{h.security_code}</span>
        <span>{h.name}</span>
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
