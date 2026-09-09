export const ATTEMPT_FAILURE_MESSAGES = {
  ADDRESS_NOT_FOUND: '收货地址不存在。',
  SHOP_NOT_FOUND: '店铺不存在。',
  PRODUCT_NOT_FOUND: '部分商品不存在。',
  SHOP_DELIVERY_CONFIG_NOT_CONFIGURED: '店铺配送范围尚未配置。',
  OUTSIDE_DELIVERY_AREA: '收货地址超出配送范围。',
  SHOP_UNAVAILABLE: '店铺当前暂停接单。',
  SHOP_CLOSED: '店铺当前不在营业时间。',
  PRODUCT_UNAVAILABLE: '部分商品当前不可售。',
  INSUFFICIENT_STOCK: '商品库存不足。',
  MINIMUM_ORDER_AMOUNT: '未达到最低起送金额。',
  INVENTORY_CHANGED: '库存已经发生变化。',
};

export function attemptFailureMessage(code) {
  return ATTEMPT_FAILURE_MESSAGES[code] || '订单创建失败，请检查后重新提交。';
}

export function progressMessage(progress) {
  if (progress.phase === 'submitting') {
    return `正在提交订单（${progress.attempt}/${progress.total}）……`;
  }
  if (progress.phase === 'confirming') {
    return '请求结果暂时未知，正在查询订单状态……';
  }
  if (progress.phase === 'retry_wait') {
    return `网络波动，${Math.ceil(progress.delayMs / 1000)}秒后进行第 ${progress.attempt}/${progress.total} 次尝试……`;
  }
  if (progress.phase === 'final_confirming') {
    return `正在进行最终确认（${progress.attempt}/${progress.total}）……`;
  }
  return '正在确认订单结果……';
}
