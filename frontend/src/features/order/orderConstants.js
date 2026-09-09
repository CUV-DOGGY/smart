export const ORDER_STATUS_LABELS = {
  pending_payment: '待支付',
  paid: '已支付',
  preparing: '备餐中',
  delivering: '配送中',
  completed: '已完成',
  canceling: '取消中',
  canceled: '已取消',
  refunded: '已退款',
};

export const CANCELLABLE_ORDER_STATUSES = new Set([
  'pending_payment',
  'paid',
  'preparing',
]);
