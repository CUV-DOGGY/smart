import { Link } from 'react-router-dom';

import { formatDeliveryAddress } from '../addressFormatting.js';
import { cartGoodsTotal } from '../cart.js';
import { formatMoney } from '../shopFormatting.js';

export function CheckoutOrderDetail({
  shop,
  cartList,
  addresses,
  addressId,
  validationError,
  isSubmitting,
  onAddressChange,
  onClose,
  onSubmit,
}) {
  const goodsTotal = cartGoodsTotal(cartList);
  const orderTotal = goodsTotal + shop.delivery_fee;
  const belowMinimum = goodsTotal < shop.minimum_order_amount;

  return (
    <div className="modal-backdrop">
      <section
        className="modal order-modal checkout-detail-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="checkout-detail-title"
      >
        <header>
          <div>
            <p className="eyebrow">ORDER DETAIL</p>
            <h2 id="checkout-detail-title">确认订单</h2>
            <p>{shop.shop_name}</p>
          </div>
          <button
            type="button"
            className="icon-button"
            disabled={isSubmitting}
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="checkout-detail-body">
          <div className="checkout-item-list">
            {cartList.map(({ product, quantity }) => (
              <div key={product.food_id}>
                <span>{product.food_name}</span>
                <span>
                  {formatMoney(product.price)} × {quantity}
                </span>
                <strong>{formatMoney(product.price * quantity)}</strong>
              </div>
            ))}
          </div>

          <label>
            收货地址
            <select
              value={addressId}
              disabled={isSubmitting}
              onChange={(event) => onAddressChange(event.target.value)}
            >
              <option value="">请选择</option>
              {addresses.map((address) => (
                <option key={address.address_id} value={address.address_id}>
                  {formatDeliveryAddress(address)}
                </option>
              ))}
            </select>
          </label>

          {!addresses.length && (
            <div className="alert warning">
              请先新增收货地址。<Link to="/addresses">前往地址管理</Link>
            </div>
          )}
          {belowMinimum && (
            <div className="alert warning">
              还差 {formatMoney(shop.minimum_order_amount - goodsTotal)}
              达到起送金额。
            </div>
          )}
          {validationError && (
            <div className="alert error">{validationError}</div>
          )}

          <dl className="checkout-totals">
            <div>
              <dt>商品金额</dt>
              <dd>{formatMoney(goodsTotal)}</dd>
            </div>
            <div>
              <dt>配送费</dt>
              <dd>{formatMoney(shop.delivery_fee)}</dd>
            </div>
            <div className="total">
              <dt>预计合计</dt>
              <dd>{formatMoney(orderTotal)}</dd>
            </div>
          </dl>
        </div>

        <footer>
          <button
            type="button"
            className="secondary"
            disabled={isSubmitting}
            onClick={onClose}
          >
            返回修改
          </button>
          <button
            type="button"
            className="primary"
            disabled={
              isSubmitting || !addressId || !cartList.length || belowMinimum
            }
            onClick={onSubmit}
          >
            {isSubmitting ? '提交中…' : `提交订单 · ${formatMoney(orderTotal)}`}
          </button>
        </footer>
      </section>
    </div>
  );
}
