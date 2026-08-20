import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MapPicker } from './MapPicker.jsx';


const mount = vi.fn();

vi.mock('./amapAdapter.js', () => ({
  AmapPickerAdapter: class {
    mount(...args) { return mount(...args); }
    destroy() {}
  },
  amapError: (error, fallback) => (
    error instanceof Error ? error : new Error(typeof error === 'string' ? error : fallback)
  ),
}));

afterEach(() => {
  cleanup();
  mount.mockReset();
});

describe('MapPicker', () => {
  it('does not render React children inside the SDK-owned map container', () => {
    mount.mockReturnValue(new Promise(() => {}));
    const { container } = render(
      <MapPicker initialValue={null} onConfirm={() => {}} onClose={() => {}} />,
    );

    expect(container.querySelector('.map-container')).toBeEmptyDOMElement();
    expect(screen.getByText('地图加载中…')).toHaveClass('map-loading');
  });

  it('keeps the dialog visible and explains loader failures', async () => {
    mount.mockRejectedValue('INVALID_USER_KEY');
    render(<MapPicker initialValue={null} onConfirm={() => {}} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('INVALID_USER_KEY')).toBeInTheDocument();
    });
    expect(screen.getByRole('dialog', { name: '地图选点' })).toBeInTheDocument();
  });
});
