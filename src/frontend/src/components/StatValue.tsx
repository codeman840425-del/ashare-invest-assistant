import { Tag, Tooltip } from 'antd';
import type { Stat } from '../api/types';

/**
 * 统计值（契约 Stat）：数字旁总是显示样本量 n；small_sample 时加“样本少”标记；n < 5 时 value=null，显示“样本不足”。
 * kind=pct 把小数按百分比显示；ratio 保留两位小数；raw 原样显示服务端 decimal 字符串，不舍入
 * （评审 05d8a16 m1：单位与口径未定时不能把 0.003 显示成 0.00）。
 */
export function StatValue({ s, kind = 'pct', testId }: { s: Stat; kind?: 'pct' | 'ratio' | 'raw'; testId?: string }) {
  const v = s.value === null ? null : Number(s.value);
  const text = v === null || !Number.isFinite(v) ? '样本不足' : kind === 'raw' ? String(s.value) : kind === 'pct' ? `${(v * 100).toFixed(1)}%` : v.toFixed(2);
  return (
    <span className="stat-value" data-testid={testId}>
      <b className="mono">{text}</b>
      <span className="muted small mono"> n={s.n}</span>
      {s.small_sample ? (
        <Tooltip title={`样本量 ${s.n} 少于 30，统计结果波动大，仅供参考（窗口 ${s.window}）`}>
          <Tag color="warning" variant="outlined" style={{ marginInlineStart: 4 }}>样本少</Tag>
        </Tooltip>
      ) : null}
    </span>
  );
}
