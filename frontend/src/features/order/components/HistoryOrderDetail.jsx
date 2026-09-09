import {
  CANCELLABLE_ORDER_STATUSES,
  ORDER_STATUS_LABELS,
} from '../orderConstants.js';
import { formatMoney } from '../shopFormatting.js';

export function HistoryOrderDetail({ order, onClose, onCancel }) {
  const cancellable = CANCELLABLE_ORDER_STATUSES.has(order.order_status);

  return (
    <div className="modal-backdrop">
      <section className="modal order-modal" role="dialog" aria-modal="true">
        <header>
          <div>
            <p className="eyebrow">ORDER DETAIL</p>
            <h2>订单详情</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose}>
            ×
          </button>
        </header>
        <dl>
          <dt>订单号</dt>
          <dd>{order.order_id}</dd>
          <dt>状态</dt>
          <dd>{ORDER_STATUS_LABELS[order.order_status] || order.order_status}</dd>
          <dt>店铺</dt>
          <dd>{order.shop_id}</dd>
          <dt>商品</dt>
          <dd>
            {order.items
              .map((item) => `${item.food_name} ×${item.quantity}`)
              .join('、')}
          </dd>
          <dt>总金额</dt>
          <dd>{formatMoney(order.total_price)}</dd>
        </dl>
        <footer>
          {cancellable && (
            <button
              type="button"
              className="danger-button"
              onClick={() => onCancel(order.order_id)}
            >
              取消订单
            </button>
          )}
          <button type="button" className="primary" onClick={onClose}>
            关闭
          </button>
        </footer>
      </section>
    </div>
  );
}
