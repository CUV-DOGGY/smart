import {
  formatBusinessHours,
  formatMoney,
  formatShopAddress,
} from '../shopFormatting.js';

export function ShopItem({ shop, onSelect }) {
  return (
    <article className="shop-item">
      <button type="button" onClick={() => onSelect(shop.shop_id)}>
        <div className="shop-item-heading">
          <h2>{shop.shop_name}</h2>
          <span
            className={`badge ${shop.is_accepting_orders ? '' : 'paused'}`}
          >
            {shop.is_accepting_orders ? '接单中' : '暂停接单'}
          </span>
        </div>
        <p>{formatShopAddress(shop)}</p>
        <dl className="shop-item-meta">
          <div className="business-hours-row">
            <dt>营业时间</dt>
            <dd>{formatBusinessHours(shop.business_hours)}</dd>
          </div>
          <div>
            <dt>配送费</dt>
            <dd>{formatMoney(shop.delivery_fee)}</dd>
          </div>
          <div>
            <dt>起送金额</dt>
            <dd>{formatMoney(shop.minimum_order_amount)}</dd>
          </div>
        </dl>
      </button>
    </article>
  );
}
