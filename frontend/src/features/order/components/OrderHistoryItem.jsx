import { ORDER_STATUS_LABELS } from '../orderConstants.js';
import { formatMoney } from '../shopFormatting.js';

export function OrderHistoryItem({ order, onSelect }) {
  return (
    <article onClick={() => onSelect(order.order_id)}>
      <div>
        <strong>
          {order.items
            .map((item) => `${item.food_name} ×${item.quantity}`)
            .join('、')}
        </strong>
        <small>
          {new Date(order.create_time).toLocaleString()} · {order.shop_id}
        </small>
      </div>
      <div>
        <span className="badge">
          {ORDER_STATUS_LABELS[order.order_status] || order.order_status}
        </span>
        <strong>{formatMoney(order.total_price)}</strong>
      </div>
    </article>
  );
}
