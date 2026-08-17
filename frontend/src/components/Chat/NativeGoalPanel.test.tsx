import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { NativeGoalPanel } from './NativeGoalPanel';
import { api } from '../../api/client';
import type { NativeGoal } from '../../api/client';

vi.mock('../../api/client', () => ({
  api: {
    getNativeGoal: vi.fn(),
    setNativeGoalStatus: vi.fn(),
    cancelNativeGoal: vi.fn(),
  },
}));

const activeGoal: NativeGoal = {
  threadId: 'thread-goal',
  objective: 'Finish the retained objective',
  status: 'active',
  tokensUsed: 123,
  tokenBudget: null,
  timeUsedSeconds: 45,
  createdAt: 1,
  updatedAt: 2,
};

describe('NativeGoalPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getNativeGoal).mockResolvedValue({ goal: activeGoal });
    vi.mocked(api.cancelNativeGoal).mockResolvedValue({
      goal: null,
      cancelled: true,
    });
  });

  it('pauses an active Goal without deleting it', async () => {
    const paused = { ...activeGoal, status: 'paused' as const };
    vi.mocked(api.setNativeGoalStatus).mockResolvedValue({
      goal: paused,
      accepted: true,
      queued: false,
    });

    render(<NativeGoalPanel taskId={13} />);
    fireEvent.click(screen.getByRole('button', { name: '查看 Goal' }));
    fireEvent.click(await screen.findByRole('button', { name: '暂停 Goal' }));

    await waitFor(() => {
      expect(api.setNativeGoalStatus).toHaveBeenCalledWith(13, 'paused');
    });
    expect(await screen.findByText('已暂停')).toBeInTheDocument();
    expect(api.cancelNativeGoal).not.toHaveBeenCalled();
  });

  it('resumes a paused Goal and preserves the delete confirmation', async () => {
    const paused = { ...activeGoal, status: 'paused' as const };
    vi.mocked(api.getNativeGoal).mockResolvedValue({ goal: paused });
    vi.mocked(api.setNativeGoalStatus).mockResolvedValue({
      goal: paused,
      accepted: true,
      queued: true,
    });

    render(<NativeGoalPanel taskId={17} />);
    fireEvent.click(screen.getByRole('button', { name: '查看 Goal' }));
    fireEvent.click(await screen.findByRole('button', { name: '启用 Goal' }));

    await waitFor(() => {
      expect(api.setNativeGoalStatus).toHaveBeenCalledWith(17, 'active');
    });

    fireEvent.click(screen.getByRole('button', { name: '删除 Goal' }));
    expect(api.cancelNativeGoal).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '再次点击确认删除' }));
    await waitFor(() => expect(api.cancelNativeGoal).toHaveBeenCalledWith(17));
  });
});
