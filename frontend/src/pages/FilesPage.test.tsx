import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  listProjects: vi.fn(),
  listWorkers: vi.fn(),
  listDir: vi.fn(),
  getProjectAgentsMd: vi.fn(),
  updateProjectAgentsMd: vi.fn(),
}));

vi.mock('../api/client', () => ({
  api: apiMocks,
  getToken: () => 'test-token',
}));

import { FilesPage } from './FilesPage';

const project = {
  id: 7,
  name: 'Demo project',
  local_path: '/srv/demo',
  location: 'local',
};

describe('FilesPage AGENTS.md editor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    localStorage.setItem('cc_user', JSON.stringify({ id: 1, role: 'admin' }));
    apiMocks.listProjects.mockResolvedValue([project]);
    apiMocks.listWorkers.mockResolvedValue([]);
    apiMocks.listDir.mockResolvedValue({ path: '/srv/demo', entries: [] });
    apiMocks.getProjectAgentsMd.mockResolvedValue({
      content: '# Existing rules\n',
      exists: true,
    });
    apiMocks.updateProjectAgentsMd.mockImplementation(
      async (_projectId: number, content: string) => ({ content, exists: true }),
    );
  });

  it('loads and saves the root AGENTS.md for a selected project', async () => {
    const user = userEvent.setup();
    render(<FilesPage />);

    const selector = await screen.findByRole('combobox');
    await user.selectOptions(selector, '7');
    await waitFor(() => expect(apiMocks.listDir).toHaveBeenCalledWith('/srv/demo'));

    await user.click(screen.getByRole('button', { name: 'Edit AGENTS.md' }));
    const editor = await screen.findByRole('textbox', { name: 'AGENTS.md content' });
    expect(editor).toHaveValue('# Existing rules\n');

    fireEvent.change(editor, { target: { value: '# Updated rules\n' } });
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(apiMocks.updateProjectAgentsMd).toHaveBeenCalledWith(
        7,
        '# Updated rules\n',
      );
    });
    expect(await screen.findByText('Saved')).toBeInTheDocument();
  });

  it('does not expose the project editor for a manually entered directory', async () => {
    const user = userEvent.setup();
    render(<FilesPage />);
    await screen.findByRole('combobox');

    const pathInput = screen.getByPlaceholderText('/path/to/directory');
    await user.type(pathInput, '/tmp/manual');
    await user.click(screen.getByRole('button', { name: 'Browse' }));

    await waitFor(() => expect(apiMocks.listDir).toHaveBeenCalledWith('/tmp/manual'));
    expect(screen.queryByRole('button', { name: 'Edit AGENTS.md' })).not.toBeInTheDocument();
  });
});
