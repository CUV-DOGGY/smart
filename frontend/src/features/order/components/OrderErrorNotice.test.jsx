import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { OrderErrorNotice } from './OrderErrorNotice.jsx';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('OrderErrorNotice', () => {
  it('counts down from three seconds', () => {
    vi.useFakeTimers();
    render(
      <OrderErrorNotice
        error={{
          code: 'SHOP_CLOSED',
          message: '店铺当前不在营业时间',
          requestId: 'request-001',
        }}
      />,
    );

    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.queryByText('SHOP_CLOSED')).not.toBeInTheDocument();
    expect(screen.queryByText('request-001')).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText('2')).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText('1')).toBeInTheDocument();
  });
});
