import { useMemo, useState } from 'react';
import { Button, Tooltip } from 'antd';
import { BorderOuterOutlined, MenuFoldOutlined, MenuUnfoldOutlined, ReloadOutlined, VerticalAlignBottomOutlined } from '@ant-design/icons';
import { Group, Panel, Separator, useDefaultLayout, useGroupRef, usePanelRef } from 'react-resizable-panels';
import { useNavigate } from 'react-router';
import { useSuggestion, useTerminal } from '../../api/queries';
import type { TerminalRow, TerminalScope } from '../../api/types';
import { ErrorBox } from '../../components/common';
import { SESSION } from '../../i18n/labels';
import { fmtTime } from '../../lib/format';
import { AccountStrip, WatchTable } from './WatchTable';
import { ChartPanel } from './ChartPanel';
import { SuggestionPanel } from './SuggestionPanel';
import { BottomPanel } from './BottomPanel';
import { DEFAULT_H, DEFAULT_V, LAYOUT_H_ID, LAYOUT_V_ID } from './layout';

export function TerminalPage() {
  const navigate = useNavigate();
  const [scope, setScope] = useState<TerminalScope>('all');
  const [selected, setSelected] = useState<string | null>(null);
  const terminal = useTerminal(scope);
  const rows = useMemo(() => terminal.data?.rows ?? [], [terminal.data]);
  const current: TerminalRow | undefined = rows.find((r) => r.security_code === selected) ?? rows[0];
  const sug = useSuggestion(current?.suggestion?.id);

  const h = useDefaultLayout({ id: LAYOUT_H_ID, storage: localStorage });
  const v = useDefaultLayout({ id: LAYOUT_V_ID, storage: localStorage });
  const hRef = useGroupRef();
  const vRef = useGroupRef();
  const leftRef = usePanelRef();
  const rightRef = usePanelRef();
  const bottomRef = usePanelRef();
  const [collapsed, setCollapsed] = useState({ left: false, right: false, bottom: false });
  const syncCollapsed = () =>
    setCollapsed({
      left: !!leftRef.current?.isCollapsed(),
      right: !!rightRef.current?.isCollapsed(),
      bottom: !!bottomRef.current?.isCollapsed(),
    });

  const toggle = (ref: typeof leftRef) => {
    const p = ref.current;
    if (!p) return;
    if (p.isCollapsed()) p.expand();
    else p.collapse();
    syncCollapsed();
  };
  const resetLayout = () => {
    hRef.current?.setLayout({ ...DEFAULT_H });
    vRef.current?.setLayout({ ...DEFAULT_V });
    syncCollapsed();
  };

  const select = (code: string) => setSelected(code);
  const open = (r: TerminalRow) => r.suggestion && navigate(`/suggestions/${r.suggestion.id}`);

  return (
    <div className="terminal" data-testid="terminal">
      <div className="term-toolbar">
        <span className="panel-title">交易终端</span>
        {terminal.data ? (
          <span className="muted small">
            {SESSION[terminal.data.session]} · 交易日 {terminal.data.trade_date} · 服务器时间 {fmtTime(terminal.data.server_time)}{terminal.data.truncated ? " · 列表已截断" : ""}
          </span>
        ) : null}
        <span className="spacer" />
        <Tooltip title={collapsed.left ? '展开左栏' : '收起左栏'}>
          <Button size="small" type="text" icon={collapsed.left ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => toggle(leftRef)} aria-label="切换左栏" />
        </Tooltip>
        <Tooltip title={collapsed.bottom ? '展开底部面板' : '收起底部面板'}>
          <Button size="small" type="text" icon={<VerticalAlignBottomOutlined />} onClick={() => toggle(bottomRef)} aria-label="切换底部面板" />
        </Tooltip>
        <Tooltip title={collapsed.right ? '展开右栏' : '收起右栏'}>
          <Button size="small" type="text" icon={<BorderOuterOutlined />} onClick={() => toggle(rightRef)} aria-label="切换右栏" />
        </Tooltip>
        <Button size="small" icon={<ReloadOutlined />} onClick={resetLayout} data-testid="reset-layout">恢复默认布局</Button>
      </div>
      {terminal.isError ? <ErrorBox error={terminal.error} /> : null}
      <div className="term-body">
        <Group
          id={LAYOUT_V_ID}
          orientation="vertical"
          groupRef={vRef}
          defaultLayout={v.defaultLayout ?? { ...DEFAULT_V }}
          onLayoutChanged={(layout, meta) => {
            v.onLayoutChanged(layout, meta);
            syncCollapsed();
          }}
        >
          <Panel id="main" minSize="40">
            <Group
              id={LAYOUT_H_ID}
              orientation="horizontal"
              groupRef={hRef}
              defaultLayout={h.defaultLayout ?? { ...DEFAULT_H }}
              onLayoutChanged={(layout, meta) => {
                h.onLayoutChanged(layout, meta);
                syncCollapsed();
              }}
            >
              <Panel id="left" panelRef={leftRef} minSize="22" collapsible collapsedSize="0">
                <section className="panel left">
                  <AccountStrip account={terminal.data?.account} />
                  <WatchTable
                    rows={rows}
                    loading={terminal.isLoading}
                    scope={scope}
                    onScope={setScope}
                    selected={current?.security_code ?? null}
                    onSelect={(r) => select(r.security_code)}
                    onOpen={open}
                  />
                </section>
              </Panel>
              <Separator className="rz-sep h" data-testid="sep-left" />
              <Panel id="center" minSize="26">
                <section className="panel center center-body">
                  <ChartPanel row={current} suggestion={sug.data} tradeDate={terminal.data?.trade_date ?? null} />
                </section>
              </Panel>
              <Separator className="rz-sep h" data-testid="sep-right" />
              <Panel id="right" panelRef={rightRef} minSize="16" collapsible collapsedSize="0">
                <section className="panel right">
                  <SuggestionPanel row={current} suggestion={sug.data} loading={sug.isLoading} error={sug.error} />
                </section>
              </Panel>
            </Group>
          </Panel>
          <Separator className="rz-sep v" data-testid="sep-bottom" />
          <Panel id="bottom" panelRef={bottomRef} minSize="10" collapsible collapsedSize="0">
            <BottomPanel selected={current?.security_code ?? null} onSelect={select} />
          </Panel>
        </Group>
      </div>
    </div>
  );
}
