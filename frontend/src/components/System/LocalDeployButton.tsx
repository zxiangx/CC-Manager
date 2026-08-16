import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowUpCircle, RefreshCw, X } from '../icons';
import { api } from '../../api/client';
import { useWebSocket } from '../../hooks/useWebSocket';

interface StepInfo {
  name: string;
  status: string;
  duration_ms?: number | null;
  message?: string | null;
}

interface DeploymentStatus {
  status?: string;
  steps?: StepInfo[];
  error?: string;
}

type Phase = 'idle' | 'confirming' | 'starting' | 'running' | 'restarting' | 'completed' | 'failed';

const ACTIVE_KEY = 'ccm-local-deploy-active';
const ACTIVE_STATUSES = new Set([
  'claimed', 'running', 'backing_up', 'restarting', 'starting',
  'stopping', 'migrating', 'rolling_back',
]);

const STEP_LABELS: Record<string, string> = {
  git_pull: '使用服务器本地代码',
  detect_changes: '检测本地变更',
  backup_database: '备份数据库',
  uv_sync: '同步 Python 依赖',
  refresh_pty: '同步 PTY 依赖',
  npm_install: '同步前端依赖',
  frontend_build: '构建前端',
  stop_service: '停止旧服务',
  alembic_upgrade: '迁移数据库',
  start_service: '启动新服务',
};

function readableError(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : '启动本地部署失败';
}

function setActive(active: boolean) {
  try {
    if (active) sessionStorage.setItem(ACTIVE_KEY, '1');
    else sessionStorage.removeItem(ACTIVE_KEY);
  } catch {
    // Hardened/private browser contexts may not expose sessionStorage.
  }
}

function wasActive(): boolean {
  try {
    return sessionStorage.getItem(ACTIVE_KEY) === '1';
  } catch {
    return false;
  }
}

export function LocalDeployButton() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [steps, setSteps] = useState<StepInfo[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState('');
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const applyStatus = useCallback((status: DeploymentStatus) => {
    if (status.steps) setSteps(status.steps);
    const value = status.status || '';
    if (value === 'completed') {
      setActive(false);
      setPhase('completed');
    } else if (value === 'failed' || value === 'rollback_failed' || value === 'rolled_back') {
      setActive(false);
      setError(status.error || '部署失败；服务已保持或恢复到安全版本');
      setPhase('failed');
    } else if (ACTIVE_STATUSES.has(value)) {
      setPhase(value === 'running' ? 'running' : 'restarting');
    }
  }, []);

  const pollStatus = useCallback(async () => {
    try {
      await api.health();
      applyStatus(await api.getUpdateStatus() as DeploymentStatus);
    } catch {
      // A short connection failure is expected while systemd replaces CCM.
      setPhase(current => current === 'running' ? 'restarting' : current);
    }
  }, [applyStatus]);

  useEffect(() => {
    if (phase !== 'running' && phase !== 'restarting') {
      if (pollTimer.current) window.clearInterval(pollTimer.current);
      pollTimer.current = null;
      return;
    }
    void pollStatus();
    pollTimer.current = window.setInterval(() => void pollStatus(), 2_000);
    return () => {
      if (pollTimer.current) window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    };
  }, [phase, pollStatus]);

  useEffect(() => {
    if (!wasActive()) return;
    setPhase('restarting');
    void pollStatus();
  }, [pollStatus]);

  const onWsMessage = useCallback((message: Record<string, unknown>) => {
    if (message.channel !== 'system_update') return;
    const data = message.data as Record<string, unknown> | undefined;
    if (!data) return;
    const event = String(data.event || '');
    if (event === 'step_update') {
      const stepName = String(data.step || '');
      setSteps(current => {
        const next = current.filter(step => step.name !== stepName);
        next.push({
          name: stepName,
          status: String(data.status || 'pending'),
          duration_ms: data.duration_ms as number | undefined,
          message: data.message as string | undefined,
        });
        return next;
      });
    } else if (event === 'log_line' && data.log) {
      setLogs(current => [...current.slice(-120), String(data.log)]);
    } else if (event === 'restarting') {
      setPhase('restarting');
    } else if (event === 'update_complete') {
      setActive(false);
      setPhase('completed');
    } else if (event === 'update_failed') {
      setActive(false);
      setError(String(data.message || '部署失败'));
      setPhase('failed');
    }
  }, []);

  useWebSocket(['system_update'], onWsMessage);

  const startDeployment = async () => {
    setError('');
    setLogs([]);
    setSteps([]);
    setPhase('starting');
    try {
      await api.deployLocalVersion();
      setActive(true);
      setPhase('running');
    } catch (requestError) {
      setActive(false);
      setError(readableError(requestError));
      setPhase('failed');
    }
  };

  const close = () => {
    setPhase('idle');
    setSteps([]);
    setLogs([]);
    setError('');
  };

  const modalOpen = phase !== 'idle';

  return (
    <>
      <button
        type="button"
        onClick={() => setPhase('confirming')}
        className="p-2 rounded text-gray-400 hover:text-foreground hover:bg-gray-800 transition-colors"
        title="部署本地版本"
        aria-label="部署本地版本"
      >
        <ArrowUpCircle size={18} />
      </button>

      {modalOpen && createPortal(
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4">
          <div className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl border border-gray-700 bg-gray-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-700 px-4 py-3">
              <h3 className="text-sm font-semibold text-foreground">
                {phase === 'confirming' && '部署服务器本地版本'}
                {phase === 'starting' && '正在部署…'}
                {phase === 'running' && '正在部署…'}
                {phase === 'restarting' && '正在重启服务…'}
                {phase === 'completed' && '部署完成'}
                {phase === 'failed' && '部署失败'}
              </h3>
              {(phase === 'confirming' || phase === 'completed' || phase === 'failed') && (
                <button type="button" onClick={close} aria-label="关闭部署窗口" className="p-1 text-gray-500 hover:text-gray-300">
                  <X size={17} />
                </button>
              )}
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {phase === 'confirming' && (
                <div className="space-y-3 text-sm text-gray-300">
                  <p>将部署服务器磁盘上当前已有的 CCM 代码，不拉取、不覆盖远端版本。</p>
                  <p className="rounded border border-amber-700/50 bg-amber-950/30 p-2 text-xs text-amber-200">
                    部署会同步依赖、重建前端、备份并迁移数据库，然后重启服务。若仍有活跃 Session，系统会拒绝部署并告诉你阻断原因。
                  </p>
                </div>
              )}

              {(phase === 'starting' || phase === 'running' || phase === 'restarting') && (
                <div className="flex items-center gap-2 text-sm text-gray-300">
                  <RefreshCw size={16} className="animate-spin text-indigo-400" />
                  {phase === 'restarting' ? '服务暂时断开属于正常现象，正在等待恢复' : '后台正在执行安全部署流程'}
                </div>
              )}

              {steps.length > 0 && (
                <div className="space-y-1 rounded border border-gray-800 bg-gray-950/50 p-2">
                  {steps.map(step => (
                    <div key={step.name} className="flex gap-2 text-xs">
                      <span>{step.status === 'completed' ? '✅' : step.status === 'failed' ? '❌' : step.status === 'running' ? '⏳' : '○'}</span>
                      <span className="flex-1 text-gray-300">{STEP_LABELS[step.name] || step.name}</span>
                      {step.duration_ms != null && <span className="text-gray-600">{(step.duration_ms / 1000).toFixed(1)}s</span>}
                    </div>
                  ))}
                </div>
              )}

              {logs.length > 0 && phase !== 'completed' && (
                <div className="max-h-36 overflow-y-auto rounded border border-gray-800 bg-gray-950 p-2 font-mono text-[11px] text-gray-500">
                  {logs.map((line, index) => <div key={index}>{line}</div>)}
                </div>
              )}

              {phase === 'completed' && (
                <div className="rounded border border-green-700/50 bg-green-950/30 p-3 text-sm text-green-300">
                  部署成功。刷新页面即可使用新版本。
                </div>
              )}
              {phase === 'failed' && (
                <div className="rounded border border-red-700/50 bg-red-950/30 p-3 text-sm text-red-300">{error}</div>
              )}
            </div>

            <div className="flex justify-end gap-2 border-t border-gray-700 px-4 py-3">
              {phase === 'confirming' && (
                <>
                  <button type="button" onClick={close} className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">取消</button>
                  <button type="button" onClick={() => void startDeployment()} className="rounded bg-indigo-600 px-3 py-1.5 text-xs text-white hover:bg-indigo-500">开始部署</button>
                </>
              )}
              {phase === 'completed' && (
                <button type="button" onClick={() => window.location.reload()} className="rounded bg-indigo-600 px-3 py-1.5 text-xs text-white hover:bg-indigo-500">刷新页面</button>
              )}
              {phase === 'failed' && (
                <button type="button" onClick={close} className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">关闭</button>
              )}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
