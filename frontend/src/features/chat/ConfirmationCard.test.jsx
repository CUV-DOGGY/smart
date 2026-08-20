import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ConfirmationCard } from './ConfirmationCard.jsx';


afterEach(cleanup);


describe('ConfirmationCard', () => {
  const confirmation = {
    interrupt_id: 'interrupt-001',
    action: 'cancel_order',
    summary: '申请取消订单 order-001',
  };

  it('renders the server summary and emits structured decisions', () => {
    const onDecision = vi.fn();
    render(<ConfirmationCard confirmation={confirmation} onDecision={onDecision} />);
    expect(screen.getByText(confirmation.summary)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '批准执行' }));
    fireEvent.click(screen.getByRole('button', { name: '拒绝' }));
    expect(onDecision).toHaveBeenNthCalledWith(1, 'approve');
    expect(onDecision).toHaveBeenNthCalledWith(2, 'reject');
  });

  it('disables both actions while a resume request is running', () => {
    render(<ConfirmationCard confirmation={confirmation} disabled onDecision={() => {}} />);
    expect(screen.getByRole('button', { name: '批准执行' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '拒绝' })).toBeDisabled();
  });
});
