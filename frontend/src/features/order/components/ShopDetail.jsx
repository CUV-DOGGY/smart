import {
  formatBusinessHours,
  formatMoney,
  formatShopAddress,
} from '../shopFormatting.js';

export function ShopDetail({ shop }) {
  return (
    <section className="panel shop-detail-card">
      <div>
        <p className="eyebrow">SHOP DETAIL</p>
        <div className="shop-detail-heading">
          <h1>{shop.shop_name}</h1>
          <span className={`badge ${shop.is_accepting_orders ? '' : 'paused'}`}>
            {shop.is_accepting_orders ? '接单中' : '暂停接单'}
          </span>
        </div>
        <p>{formatShopAddress(shop)}</p>
        <small>{formatBusinessHours(shop.business_hours)}</small>
      </div>
      <dl>
        <div>
          <dt>配送费</dt>
          <dd>{formatMoney(shop.delivery_fee)}</dd>
        </div>
        <div>
          <dt>起送金额</dt>
          <dd>{formatMoney(shop.minimum_order_amount)}</dd>
        </div>
      </dl>
    </section>
  );
}
