/**
 * 不可变地修改某件商品的购物车数量。
 * 数量会被限制在 0 到库存之间；数量归零时会移除购物车项。
 */
export function changeCartQuantity(cartList, product, delta) {
  if (!product?.food_id || !Number.isInteger(delta) || delta === 0) {
    return cartList;
  }

  const currentItem = cartList.find(
    (item) => item.product.food_id === product.food_id,
  );
  const currentQuantity = currentItem?.quantity || 0;
  const nextQuantity = Math.max(
    0,
    Math.min(product.stock, currentQuantity + delta),
  );

  if (!currentItem && nextQuantity > 0) {
    return [...cartList, { product, quantity: nextQuantity }];
  }
  if (!currentItem) return cartList;
  if (nextQuantity === 0) {
    return cartList.filter(
      (item) => item.product.food_id !== product.food_id,
    );
  }

  return cartList.map((item) =>
    item.product.food_id === product.food_id
      ? { ...item, product, quantity: nextQuantity }
      : item,
  );
}

export function cartQuantity(cartList, foodId) {
  return (
    cartList.find((item) => item.product.food_id === foodId)?.quantity || 0
  );
}

export function cartGoodsTotal(cartList) {
  return cartList.reduce(
    (total, item) => total + item.product.price * item.quantity,
    0,
  );
}

export function cartItemCount(cartList) {
  return cartList.reduce((total, item) => total + item.quantity, 0);
}

/** 创建只包含后端允许字段的订单请求，客户端价格不会进入请求。 */
export function buildOrderPayload({ shopId, addressId, cartList }) {
  return {
    shop_id: shopId,
    address_id: addressId,
    items: cartList.map(({ product, quantity }) => ({
      food_id: product.food_id,
      quantity,
    })),
  };
}

/**
 * 生成与商品排列顺序无关的稳定指纹，用于判断是否可以复用幂等键。
 */
export function fingerprintOrderPayload(payload) {
  const normalizedPayload = {
    shop_id: payload.shop_id,
    address_id: payload.address_id,
    items: [...payload.items]
      .map(({ food_id, quantity }) => ({ food_id, quantity }))
      .sort((left, right) => left.food_id.localeCompare(right.food_id)),
  };
  return JSON.stringify(normalizedPayload);
}
