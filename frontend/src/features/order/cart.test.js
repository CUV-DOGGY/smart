import { describe, expect, it } from 'vitest';

import {
  buildOrderPayload,
  cartGoodsTotal,
  changeCartQuantity,
  fingerprintOrderPayload,
} from './cart.js';

const PRODUCT = {
  food_id: 'food-001',
  shop_id: 'shop-001',
  food_name: '测试商品',
  price: 12.5,
  stock: 2,
};

describe('cart helpers', () => {
  it('adds, limits and removes a product without mutating the previous cart', () => {
    const emptyCart = [];
    const oneItem = changeCartQuantity(emptyCart, PRODUCT, 1);
    const twoItems = changeCartQuantity(oneItem, PRODUCT, 1);
    const limited = changeCartQuantity(twoItems, PRODUCT, 1);
    const removed = changeCartQuantity(
      changeCartQuantity(twoItems, PRODUCT, -1),
      PRODUCT,
      -1,
    );

    expect(emptyCart).toEqual([]);
    expect(oneItem).toEqual([{ product: PRODUCT, quantity: 1 }]);
    expect(twoItems[0].quantity).toBe(2);
    expect(limited[0].quantity).toBe(2);
    expect(removed).toEqual([]);
  });

  it('builds a server-safe payload and calculates the goods total', () => {
    const cartList = [{ product: PRODUCT, quantity: 2 }];

    expect(cartGoodsTotal(cartList)).toBe(25);
    expect(
      buildOrderPayload({
        shopId: 'shop-001',
        addressId: 'address-001',
        cartList,
      }),
    ).toEqual({
      shop_id: 'shop-001',
      address_id: 'address-001',
      items: [{ food_id: 'food-001', quantity: 2 }],
    });
  });

  it('creates the same fingerprint regardless of item order', () => {
    const first = {
      shop_id: 'shop-001',
      address_id: 'address-001',
      items: [
        { food_id: 'food-002', quantity: 1 },
        { food_id: 'food-001', quantity: 2 },
      ],
    };
    const second = { ...first, items: [...first.items].reverse() };

    expect(fingerprintOrderPayload(first)).toBe(
      fingerprintOrderPayload(second),
    );
  });
});
