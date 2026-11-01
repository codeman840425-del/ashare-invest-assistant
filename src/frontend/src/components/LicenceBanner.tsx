import { Button } from 'antd';
import type { DataLicenceState } from '../api/enums';
import { LICENCE_BANNER_TEXT, LICENCE_NOT_SET_TEXT, LICENCE_STATUS, LICENCE_UNAVAILABLE } from '../i18n/licenceLabels';

/**
 * 全站数据证书横幅（契约 v0.2.6 变更 #8；T-A07 §5）：本人证书不可用或未设置时显示。
 * 不可用期间行情接口返回 stale / unavailable 与 gaps[data_licence_unavailable]，不报错。
 */
export function LicenceBanner({ status, onOpen }: { status: DataLicenceState | undefined; onOpen: () => void }) {
  if (!status || (status !== 'not_set' && !LICENCE_UNAVAILABLE.includes(status))) return null;
  const unavailable = status !== 'not_set';
  return (
    <div className={`licence-banner${unavailable ? ' bad' : ''}`} role="status" data-testid="licence-banner" data-status={status}>
      <span>{unavailable ? `${LICENCE_BANNER_TEXT}（${LICENCE_STATUS[status].text}）` : LICENCE_NOT_SET_TEXT}</span>
      <Button size="small" type="link" onClick={onOpen}>去设置 ›</Button>
    </div>
  );
}
