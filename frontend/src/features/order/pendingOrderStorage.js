const STORAGE_PREFIX = 'smartserve.pending-order-attempt.v1';

function storageKey(userId) {
  return `${STORAGE_PREFIX}:${encodeURIComponent(userId)}`;
}

function isPendingAttempt(value) {
  return (
    value &&
    typeof value === 'object' &&
    typeof value.key === 'string' &&
    value.key.length > 0 &&
    typeof value.fingerprint === 'string' &&
    value.fingerprint.length > 0 &&
    typeof value.createdAt === 'string' &&
    isOrderPayload(value.payload)
  );
}

function isOrderPayload(value) {
  return (
    value &&
    typeof value === 'object' &&
    typeof value.shop_id === 'string' &&
    typeof value.address_id === 'string' &&
    Array.isArray(value.items) &&
    value.items.length > 0 &&
    value.items.every(
      (item) =>
        typeof item?.food_id === 'string' &&
        Number.isInteger(item?.quantity) &&
        item.quantity > 0,
    )
  );
}

export const pendingOrderStorage = {
  //获取待确认订单操作
  get(userId) {
    if (!userId) return null;
    try {
      //用用户ID得到存储键
      const key = storageKey(userId);
      //取出存进去的待确认订单操作
      const raw = globalThis.localStorage?.getItem(key);
      if (!raw) return null;
      //将json字符串校验成对象
      const value = JSON.parse(raw);
      //检验数据是否损坏
      if (isPendingAttempt(value)) return value;
      globalThis.localStorage?.removeItem(key);
    } catch {
      // Order creation must remain available if browser storage is blocked.
    }
    return null;
  },
  //设置待确认订单操作
  set(userId, attempt) {
    if (!userId || !isPendingAttempt(attempt)) return false;
    try {
      globalThis.localStorage?.setItem(
        storageKey(userId),
        JSON.stringify(attempt),
      );
      return true;
    } catch {
      return false;
    }
  },
  //清除待确认订单操作
  clear(userId, expectedKey = null) {
    if (!userId) return false;
    try {
      const key = storageKey(userId);
      if (expectedKey) {
        const raw = globalThis.localStorage?.getItem(key);
        if (!raw) return false;
        const current = JSON.parse(raw);
        if (current?.key !== expectedKey) return false;
      }
      globalThis.localStorage?.removeItem(key);
      return true;
    } catch {
      return false;
    }
  },
};
