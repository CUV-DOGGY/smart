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

  it('renders a server-priced order table and order-specific actions', () => {
    const onDecision = vi.fn();
    const orderConfirmation = {
      interrupt_id: 'interrupt-order-001',
      action: 'create_order',
      summary: '请确认来自 测试店铺 的订单',
      presentation: {
        kind: 'order',
        shop_id: 'shop-001',
        shop_name: '测试店铺',
        address_id: 'address-001',
        receiver_name: '小高',
        receiver_phone: '138****8000',
        delivery_address: '北京市朝阳区测试路1号',
        items: [
          {
            food_id: 'food-001',
            food_name: '香辣鸡腿堡',
            quantity: 2,
            unit_price: 18.5,
            line_total: 37,
          },
        ],
        goods_amount: 37,
        delivery_fee: 5,
        total_price: 42,
        currency: 'CNY',
      },
    };

    render(<ConfirmationCard confirmation={orderConfirmation} onDecision={onDecision} />);

    expect(screen.getByRole('table')).toHaveTextContent('香辣鸡腿堡');
    expect(screen.getByText('小高 · 138****8000')).toBeInTheDocument();
    expect(screen.getByText('北京市朝阳区测试路1号')).toBeInTheDocument();
    expect(screen.getByText('¥42.00')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认下单 · ¥42.00' }));
    fireEvent.click(screen.getByRole('button', { name: '取消下单' }));
    expect(onDecision).toHaveBeenNthCalledWith(1, 'approve');
    expect(onDecision).toHaveBeenNthCalledWith(2, 'reject');
  });
});
