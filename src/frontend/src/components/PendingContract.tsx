import { Tag } from 'antd';

/** 契约还没给出结构的部分：只占位并标“待契约”，不发请求、不猜字段（T-F12） */
export function PendingContract({ what, testId }: { what: string; testId: string }) {
  return (
    <div className="pending-contract small" data-testid={testId}>
      <Tag color="default">待契约</Tag><span className="muted">{what}：契约尚未给出，暂不展示</span>
    </div>
  );
}
