import { configureStore } from '@reduxjs/toolkit';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import authReducer from '../auth/authSlice.js';
import { OrderCenterLayout } from './OrderCenterLayout.jsx';
import { orderApi } from './api.js';
import { pendingOrderStorage } from './pendingOrderStorage.js';

vi.mock('./api.js', () => ({
  orderApi: {
    create: vi.fn(),
    findByIdempotencyKey: vi.fn(),
  },
}));

const USER_ID = 'user-001';
const ATTEMPT = {
  fingerprint: '{"shop_id":"shop-001"}',
  key: 'web-checkout-001',
  createdAt: '2026-08-28T00:00:00.000Z',
  payload: {
    shop_id: 'shop-001',
    address_id: 'address-001',
    items: [{ food_id: 'food-001', quantity: 1 }],
  },
};

function renderOrderRoutes() {
  const store = configureStore({
    reducer: { auth: authReducer },
    preloadedState: {
      auth: {
        status: 'authenticated',
        user: { user_id: USER_ID, username: 'tester' },
      },
    },
  });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/orders/shops']}>
        <Routes>
          <Route path="/orders" element={<OrderCenterLayout />}>
            <Route path="shops" element={<div>店铺列表内容</div>} />
            <Route path="history" element={<div>历史订单内容</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </Provider>,
  );
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
});

describe('OrderCenterLayout pending order recovery', () => {
  it('navigates only after the server reports a succeeded order', async () => {
    pendingOrderStorage.set(USER_ID, ATTEMPT);
    orderApi.findByIdempotencyKey.mockResolvedValue({
      status: 'succeeded',
      order: {
        order_id: 'order-001',
        total_price: 30,
      },
    });

    renderOrderRoutes();

    expect(await screen.findByText('历史订单内容')).toBeInTheDocument();
    expect(pendingOrderStorage.get(USER_ID)).toBeNull();
  });

  it('keeps an unknown attempt when the user exits confirmation', async () => {
    pendingOrderStorage.set(USER_ID, ATTEMPT);
    orderApi.findByIdempotencyKey.mockResolvedValue({ status: 'not_found' });

    renderOrderRoutes();

    fireEvent.click(await screen.findByText('退出并稍后确认'));
    await waitFor(() => {
      expect(
        screen.queryByText('订单结果尚未确认'),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByText('店铺列表内容')).toBeInTheDocument();
    expect(pendingOrderStorage.get(USER_ID)).toEqual(ATTEMPT);
    expect(
      screen.getByText('有一笔订单结果尚未确认，请勿重复下单。'),
    ).toBeInTheDocument();
  });
});
