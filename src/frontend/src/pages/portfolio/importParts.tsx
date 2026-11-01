import { useState } from 'react';
import { Button, Input, Radio, Space, Tag, Tooltip } from 'antd';
import type { ImportFinding } from '../../api/accountTypes';
import { IMPORT_TONE, findingText, findingTone, importCodeSpec } from '../../api/importCodes';
import { OVERRIDE_CHOICES, choiceText } from '../../i18n/importLabels';

export function FindingTag({ f }: { f: ImportFinding }) {
  const spec = importCodeSpec(f.code, f.severity);
  const tone = IMPORT_TONE[findingTone(f)];
  return (
    <Tooltip title={<div><div>{findingText(f)}</div>{spec.handling ? <div className="muted">处理：{spec.handling}</div> : null}<div className="mono muted">{f.code}</div></div>}>
      <Tag color={tone.tag} data-code={f.code}>{spec.title}{f.resolution ? ' ✓' : ''}</Tag>
    </Tooltip>
  );
}

/** 图例：四种着色的含义 */
export function ToneLegend() {
  return (
    <Space size={4} wrap className="imp-legend" data-testid="tone-legend">
      {Object.entries(IMPORT_TONE).map(([k, t]) => <Tag key={k} color={t.tag}>{t.label}</Tag>)}
    </Space>
  );
}

/** 一条提示（文件级或行级）及其处理控件 */
export function FindingItem({ f, onResolve, busy, readOnly }: { f: ImportFinding; onResolve?: (choice: string, reason: string | null) => void; busy?: boolean; readOnly?: boolean }) {
  const spec = importCodeSpec(f.code, f.severity);
  const tone = findingTone(f);
  const [choice, setChoice] = useState<string | undefined>(f.resolution?.choice ?? f.default_resolution ?? undefined);
  const [reason, setReason] = useState(f.resolution?.reason ?? '');
  const needReason = !!choice && OVERRIDE_CHOICES.has(choice);
  return (
    <div className={`imp-finding ${IMPORT_TONE[tone].rowClass}`} data-testid={`finding-${f.id}`}>
      <div className="imp-finding-head">
        <FindingTag f={f} />
        {f.row_no != null ? <span className="mono muted">第 {f.row_no} 行</span> : <span className="muted">文件</span>}
        {f.field ? <span className="mono muted">{f.field}</span> : null}
        <span>{findingText(f)}</span>
      </div>
      {spec.handling ? <div className="muted imp-handling">处理：{spec.handling}</div> : null}
      {f.needs_action && !readOnly ? (
        <div className="imp-resolve">
          <Radio.Group value={choice} onChange={(e) => setChoice(e.target.value as string)}>
            {f.resolution_choices.map((c) => (
              <Radio key={c} value={c}>{choiceText(c)}{c === f.default_resolution ? <span className="muted">（默认）</span> : null}</Radio>
            ))}
          </Radio.Group>
          {needReason ? (
            <Input size="small" placeholder="覆盖默认处理，必须填写理由（写入审计）" value={reason} onChange={(e) => setReason(e.target.value)} style={{ maxWidth: 360 }} data-testid={`reason-${f.id}`} />
          ) : null}
          <Button size="small" type={f.resolution ? 'default' : 'primary'} loading={busy} disabled={!choice || (needReason && !reason.trim())}
            onClick={() => onResolve?.(choice!, reason.trim() || null)} data-testid={`resolve-${f.id}`}>
            {f.resolution ? '更新处理' : '确认处理'}
          </Button>
          {f.resolution ? <span className="muted">已处理：{choiceText(f.resolution.choice)}{f.resolution.reason ? `（${f.resolution.reason}）` : ''}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
