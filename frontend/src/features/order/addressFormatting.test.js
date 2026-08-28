import { describe, expect, it } from 'vitest';

import { formatDeliveryAddress } from './addressFormatting.js';

describe('formatDeliveryAddress', () => {
  it('includes receiver, phone and the complete regional address', () => {
    expect(
      formatDeliveryAddress({
        receiver_name: '小狗仔',
        receiver_phone: '13800138000',
        province: '广东省',
        city: '深圳市',
        district: '南山区',
        detail_address: '科技园1号',
      }),
    ).toBe('小狗仔 · 13800138000 · 广东省深圳市南山区科技园1号');
  });

  it('does not repeat a municipality name', () => {
    expect(
      formatDeliveryAddress({
        receiver_name: '小明',
        receiver_phone: '13900139000',
        province: '上海市',
        city: '上海市',
        district: '浦东新区',
        detail_address: '世纪大道8号',
      }),
    ).toBe('小明 · 13900139000 · 上海市浦东新区世纪大道8号');
  });
});
