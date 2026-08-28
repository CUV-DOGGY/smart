import { cartGoodsTotal, cartItemCount } from '../cart.js';
import { formatMoney } from '../shopFormatting.js';

export function Cart({
  cartList,
  expanded,
  purchaseDisabled,
  onToggle,
  onPurchase,
}) {
  const itemCount = cartItemCount(cartList);
  const goodsTotal = cartGoodsTotal(cartList);
  const hasItems = cartList.length > 0;

  return (
    <section className="cart-bar" aria-label="购物车">
      {expanded && hasItems && (
        <div className="cart-items">
          {cartList.map(({ product, quantity }) => (
            <div key={product.food_id}>
              <span>{product.food_name}</span>
              <span>× {quantity}</span>
              <strong>{formatMoney(product.price * quantity)}</strong>
            </div>
          ))}
        </div>
      )}

      <button
        type="button"
        className="cart-toggle"
        aria-expanded={expanded}
        onClick={onToggle}
      >
        <span className="cart-icon" aria-hidden="true">
          🛒
        </span>
        <span>
          <strong>{itemCount ? `${itemCount} 件商品` : '购物车为空'}</strong>
          <small>{hasItems ? '点击查看已选商品' : '请选择商品'}</small>
        </span>
        <strong>{formatMoney(goodsTotal)}</strong>
      </button>

      {hasItems && (
        <button
          type="button"
          className="primary cart-purchase"
          disabled={purchaseDisabled}
          onClick={onPurchase}
        >
          购买
        </button>
      )}
    </section>
  );
}
