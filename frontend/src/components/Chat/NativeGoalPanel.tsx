import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import type { NativeGoal } from '../../api/client';
import { ListTodo, Loader2, RefreshCw, Trash2, X } from '../icons';

interface NativeGoalPanelProps {
  taskId: number;
  onCancelled?: () => void;
}

const statusPresentation: Record<string, { label: string; classes: string }> = {
  active: { label: '运行中', classes: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  paused: { label: '已暂停', classes: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  blocked: { label: '已阻塞', classes: 'bg-orange-500/15 text-orange-300 border-orange-500/30' },
  usageLimited: { label: '额度受限', classes: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  budgetLimited: { label: '预算已达上限', classes: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  complete: { label: '已完成', classes: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
};

function formatCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}小时 ${minutes}分钟`;
  if (minutes > 0) return `${minutes}分钟`;
  return `${seconds}秒`;
}

function formatGoalTime(value: number): string {
  const milliseconds = value < 10_000_000_000 ? value * 1000 : value;
  return new Date(milliseconds).toLocaleString();
}

export function NativeGoalPanel({ taskId, onCancelled }: NativeGoalPanelProps) {
  const [open, setOpen] = useState(false);
  const [goal, setGoal] = useState<NativeGoal | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelArmed, setCancelArmed] = useState(false);

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const result = await api.getNativeGoal(taskId);
      setGoal(result.goal);
      setLoaded(true);
      setError(null);
    } catch (requestError) {
      if (!quiet) {
        setError(requestError instanceof Error ? requestError.message : String(requestError));
      }
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    void refresh(true);
    const timer = window.setInterval(() => void refresh(true), open ? 5_000 : 15_000);
    return () => window.clearInterval(timer);
  }, [open, refresh]);

  useEffect(() => {
    setGoal(null);
    setLoaded(false);
    setError(null);
    setCancelArmed(false);
  }, [taskId]);

  const cancelGoal = async () => {
    if (!cancelArmed) {
      setCancelArmed(true);
      return;
    }
    setCancelling(true);
    setError(null);
    try {
      await api.cancelNativeGoal(taskId);
      setGoal(null);
      setLoaded(true);
      setCancelArmed(false);
      onCancelled?.();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : String(requestError));
    } finally {
      setCancelling(false);
    }
  };

  const presentation = goal
    ? (statusPresentation[goal.status] || { label: goal.status, classes: 'bg-gray-700 text-gray-300 border-gray-600' })
    : null;

  return (
    <>
      <button
        type="button"
        onClick={() => { setOpen(true); void refresh(); }}
        className={`relative p-1.5 transition-colors ${goal ? 'text-emerald-300 hover:text-emerald-200' : 'text-gray-600 hover:text-gray-300'}`}
        title={goal ? `Goal：${presentation?.label}` : '查看 Goal'}
        aria-label="查看 Goal"
      >
        <ListTodo size={18} />
        {goal && goal.status !== 'complete' && (
          <span className={`absolute right-0.5 top-0.5 h-2 w-2 rounded-full border border-gray-900 ${goal.status === 'active' ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
        )}
      </button>

      {open && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/65 p-4" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !cancelling) setOpen(false);
        }}>
          <div className="flex max-h-[82vh] w-full max-w-xl flex-col overflow-hidden rounded-xl border border-gray-700 bg-gray-800 shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-700 bg-gray-900/70 px-4 py-3">
              <div className="flex items-center gap-2">
                <ListTodo size={18} className="text-emerald-400" />
                <div>
                  <div className="text-sm font-semibold text-gray-100">Codex Goal</div>
                  <div className="text-[11px] text-gray-500">持久保存在原生 Codex Task 中</div>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => void refresh()} disabled={loading || cancelling} className="p-1.5 text-gray-500 hover:text-gray-300 disabled:opacity-40" title="刷新 Goal">
                  <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
                </button>
                <button type="button" onClick={() => setOpen(false)} disabled={cancelling} className="p-1.5 text-gray-500 hover:text-gray-300 disabled:opacity-40" aria-label="关闭 Goal 面板">
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className="overflow-y-auto p-4">
              {loading && !loaded ? (
                <div className="flex items-center justify-center gap-2 py-12 text-sm text-gray-400"><Loader2 size={18} className="animate-spin" />正在读取 Goal…</div>
              ) : goal ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${presentation?.classes}`}>{presentation?.label}</span>
                    <span className="text-xs text-gray-500">更新于 {formatGoalTime(goal.updatedAt)}</span>
                  </div>
                  <div className="rounded-lg border border-gray-700 bg-gray-900/60 p-3">
                    <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-gray-500">目标</div>
                    <div className="whitespace-pre-wrap break-words text-sm leading-6 text-gray-100">{goal.objective}</div>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                    <div className="rounded-lg bg-gray-900/50 p-2"><div className="text-gray-500">已用 Token</div><div className="mt-1 text-gray-200">{formatCount(goal.tokensUsed)}</div></div>
                    <div className="rounded-lg bg-gray-900/50 p-2"><div className="text-gray-500">Token 预算</div><div className="mt-1 text-gray-200">{goal.tokenBudget == null ? '不限' : formatCount(goal.tokenBudget)}</div></div>
                    <div className="rounded-lg bg-gray-900/50 p-2"><div className="text-gray-500">运行时间</div><div className="mt-1 text-gray-200">{formatDuration(goal.timeUsedSeconds)}</div></div>
                    <div className="rounded-lg bg-gray-900/50 p-2"><div className="text-gray-500">创建时间</div><div className="mt-1 text-gray-200">{formatGoalTime(goal.createdAt)}</div></div>
                  </div>
                  {goal.status !== 'complete' && (
                    <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3">
                      <div className="mb-2 text-xs text-gray-400">取消会停止正在执行的 Goal 回合，并永久清除此 Goal；之后不会再自动续跑。</div>
                      <button type="button" onClick={cancelGoal} disabled={cancelling} className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${cancelArmed ? 'bg-red-600 text-white hover:bg-red-500' : 'border border-red-500/40 text-red-300 hover:bg-red-500/10'}`}>
                        {cancelling ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        {cancelling ? '正在停止并取消…' : cancelArmed ? '再次点击确认取消' : '取消 Goal'}
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="py-12 text-center"><ListTodo size={28} className="mx-auto mb-3 text-gray-700" /><div className="text-sm text-gray-300">当前没有 Goal</div><div className="mt-1 text-xs text-gray-600">在 Codex 中创建 Goal 后，它会自动显示在这里。</div></div>
              )}
              {error && <div className="mt-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
