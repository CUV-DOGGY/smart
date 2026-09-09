import { configureStore } from '@reduxjs/toolkit';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import authReducer from '../auth/authSlice.js';
import { addressApi } from '../address/api.js';
import { OrderCenterLayout } from './OrderCenterLayout.jsx';
import { ProductDetailPage } from './ProductDetailPage.jsx';
import { orderApi } from './api.js';
import { pendingOrderStorage } from './pendingOrderStorage.js';

vi.mock('../address/api.js', () => ({
  addressApi: { list: vi.fn() },
}));

vi.mock('./api.js', () => ({
  orderApi: {
    getShop: vi.fn(),
    listProducts: vi.fn(),
    create: vi.fn(),
    findByIdempotencyKey: vi.fn(),
  },
}));

const USER_ID = 'user-001';
const SHOP = {
  shop_id: 'shop-001',
  shop_name: '测试店铺',
  is_active: true,
  is_accepting_orders: true,
  business_hours: [
    { day_of_week: 0, open_time: '09:00:00', close_time: '22:00:00' },
  ],
  minimum_order_amount: 10,
  delivery_fee: 5,
};
const PRODUCT = {
  food_id: 'food-001',
  shop_id: 'shop-001',
  food_name: '测试商品',
  price: 20,
  stock: 2,
  is_listed: true,
  is_available: true,
};

function renderProductPage() {
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
      <MemoryRouter initialEntries={['/orders/shops/shop-001']}>
        <Routes>
          <Route path="/orders" element={<OrderCenterLayout />}>
            <Route path="shops/:shopId" element={<ProductDetailPage />} />
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

describe('ProductDetailPage checkout flow', () => {
  it('restores order detail three seconds after a definitive create failure', async () => {
    orderApi.getShop.mockResolvedValue(SHOP);
    orderApi.listProducts.mockResolvedValue({ items: [PRODUCT] });
    addressApi.list.mockResolvedValue({
      items: [
        {
          address_id: 'address-001',
          receiver_name: '测试用户',
          receiver_phone: '13800138000',
          province: '广东省',
          city: '深圳市',
          district: '南山区',
          detail_address: '测试地址',
          is_default: true,
        },
      ],
    });
    orderApi.create.mockRejectedValue({
      status: 409,
      code: 'INSUFFICIENT_STOCK',
      message: '商品库存不足',
    });

    renderProductPage();

    fireEvent.click(await screen.findByLabelText('增加测试商品'));
    fireEvent.click(screen.getByText('购买'));
    fireEvent.click(screen.getByText(/提交订单/));

    expect(await screen.findByText('订单创建失败')).toBeInTheDocument();
    expect(screen.getByText('商品库存不足')).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.queryByRole('heading', { name: '确认订单' }),
      ).not.toBeInTheDocument();
    });

    await waitFor(
      () => {
        expect(
          screen.getByRole('heading', { name: '确认订单' }),
        ).toBeInTheDocument();
      },
      { timeout: 4500 },
    );
    expect(pendingOrderStorage.get(USER_ID)).toBeNull();
  });
});
