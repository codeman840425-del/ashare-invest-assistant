/**
 * T-F23 研究候选入口（契约 v0.2.9 §7.7A“关联”）：
 * 候选信号卡详情 → origin=suggestion，用 ?suggestion_id= 反查；个股页、候选信号详情 → from_stock，用 ?security_code= 反查。
 * 反查按默认状态（不含已放弃）；同一证券已有研究中 / 观察中的候选时只给链接，创建时仍以服务端 409 为准。
 */
import { useState } from 'react';
import { Button, Space, Tag, Tooltip } from 'antd';
import { Link } from 'react-router';
import { DEFAULT_CANDIDATE_STATUS, useCandidates } from '../../api/candidateQueries';
import type { SecurityType } from '../../api/enums';
import { RESEARCH_STATUS } from '../../i18n/candidateLabels';
import { CreateCandidateModal } from './CreateCandidateModal';

export function AddToResearch({ origin, securityCode, suggestionId = null, securityType = null, size = 'small' }: {
  origin: 'from_stock' | 'suggestion';
  securityCode: string;
  suggestionId?: string | null;
  /** 已知证券类型时，ETF、指数直接禁用（plan 第 9 节问题 70） */
  securityType?: SecurityType | null;
  size?: 'small' | 'middle';
}) {
  const [open, setOpen] = useState(false);
  const unsupported = securityType === 'etf' || securityType === 'index';
  const list = useCandidates(
    origin === 'suggestion'
      ? { status: DEFAULT_CANDIDATE_STATUS, suggestion_id: suggestionId ?? '' }
      : { status: DEFAULT_CANDIDATE_STATUS, security_code: securityCode },
    { enabled: !unsupported && (origin !== 'suggestion' || !!suggestionId), limit: 5 },
  );
  const linked = list.items;
  const active = linked.find((c) => c.status === 'researching' || c.status === 'watching');
  return (
    <Space size={4} wrap data-testid="add-to-research">
      {linked.map((c) => (
        <Link key={c.id} to={`/candidates/${c.id}`} data-testid={`research-link-${c.id}`}>
          <Tag color={RESEARCH_STATUS[c.status].color}>研究候选 · {RESEARCH_STATUS[c.status].text} · 第 {c.current_version_no} 版</Tag>
        </Link>
      ))}
      {active ? null : (
        <Tooltip title={unsupported ? 'ETF、指数不能加入研究候选' : '记录你的研究要点与成立条件；系统按当时数据生成理由、反证与适配提示'}>
          <Button size={size} disabled={unsupported || list.isPending} onClick={() => setOpen(true)} data-testid="add-to-research-btn">
            加入研究候选
          </Button>
        </Tooltip>
      )}
      {open ? (
        <CreateCandidateModal
          open={open}
          onClose={() => setOpen(false)}
          origin={origin}
          securityCode={securityCode}
          suggestionId={suggestionId}
          title={`加入研究候选：${securityCode}`}
        />
      ) : null}
    </Space>
  );
}
