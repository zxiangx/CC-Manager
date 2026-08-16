import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LocalDeployButton } from './LocalDeployButton';

vi.mock('../../api/client', () => ({
  api: {
    deployLocalVersion: vi.fn(),
    getUpdateStatus: vi.fn(),
    health: vi.fn(),
  },
}));

vi.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(),
}));

import { api } from '../../api/client';

describe('LocalDeployButton', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(api.deployLocalVersion).mockResolvedValue({ status: 'started' } as never);
    vi.mocked(api.getUpdateStatus).mockResolvedValue({ status: 'running' } as never);
    vi.mocked(api.health).mockResolvedValue({ status: 'ok' } as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
    sessionStorage.clear();
  });

  it('starts a local-only deployment after confirmation', async () => {
    const user = userEvent.setup();
    render(<LocalDeployButton />);

    await user.click(screen.getByTitle('部署本地版本'));
    expect(screen.getByText('不拉取、不覆盖远端版本。', { exact: false })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '开始部署' }));

    expect(api.deployLocalVersion).toHaveBeenCalledTimes(1);
    expect(screen.getByText('正在部署…')).toBeInTheDocument();
  });

  it('shows deployment admission errors such as active sessions', async () => {
    vi.mocked(api.deployLocalVersion).mockRejectedValue(
      new Error('当前有 2 个任务正在运行，请等待任务完成后再修复'),
    );
    const user = userEvent.setup();
    render(<LocalDeployButton />);

    await user.click(screen.getByTitle('部署本地版本'));
    await user.click(screen.getByRole('button', { name: '开始部署' }));

    await waitFor(() => {
      expect(screen.getByText(/当前有 2 个任务正在运行/)).toBeInTheDocument();
    });
  });
});
