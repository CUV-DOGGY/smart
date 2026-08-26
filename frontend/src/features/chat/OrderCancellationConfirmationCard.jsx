const moneyFormatter = new Intl.NumberFormat('zh-CN', {
  style: 'currency',
  currency: 'CNY',
  minimumFractionDigits: 2,
});

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
});

const statusLabels = {
  pending_payment: '待支付',
  pending_accept: '待接单',
  preparing: '备餐中',
};

function formatMoney(value) {
  return moneyFormatter.format(Number(value) || 0);
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date);
}

export function OrderCancellationConfirmationCard({
  confirmation,
  disabled,
  onDecision,
}) {
  const order = confirmation.presentation;

  return (
    <section
      className="confirmation-card order-confirmation-card order-cancellation-card"
      aria-label="待确认取消订单"
    >
      <header className="order-confirmation-header">
        <div className="order-confirmation-icon" aria-hidden="true">
          !
        </div>
        <div>
          <p className="eyebrow">CANCELLATION CONFIRMATION</p>
          <h2>请确认取消订单</h2>
          <p>{order.shop_name}</p>
        </div>
        <span className="confirmation-badge">待确认</span>
      </header>

      <div className="order-confirmation-body">
        <div className="order-confirmation-table-wrap">
          <table className="order-confirmation-table">
            <thead>
              <tr>
                <th scope="col">商品</th>
                <th scope="col">单价</th>
                <th scope="col">数量</th>
                <th scope="col">小计</th>
              </tr>
            </thead>
            <tbody>
              {order.items.map((item) => (
                <tr key={item.food_id}>
                  <td>
                    <strong>{item.food_name}</strong>
                    <small>{item.food_id}</small>
                  </td>
                  <td>{formatMoney(item.unit_price)}</td>
                  <td>× {item.quantity}</td>
                  <td>
                    <strong>{formatMoney(item.line_total)}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="order-confirmation-meta">
          <dl className="cancellation-order-meta">
            <div>
              <dt>订单号</dt>
              <dd>{order.order_id}</dd>
            </div>
            <div>
              <dt>当前状态</dt>
              <dd>{statusLabels[order.current_status] || order.current_status}</dd>
            </div>
            <div>
              <dt>下单时间</dt>
              <dd>{formatDate(order.create_time)}</dd>
            </div>
          </dl>
          <dl className="order-confirmation-totals">
            <div className="grand-total">
              <dt>订单金额</dt>
              <dd>{formatMoney(order.total_price)}</dd>
            </div>
          </dl>
        </div>
      </div>

      <footer className="order-confirmation-footer">
        <p>确认后将提交取消申请。执行前系统会再次校验订单状态。</p>
        <div className="confirmation-actions">
          <button
            className="secondary"
            disabled={disabled}
            onClick={() => onDecision('reject')}
          >
            保留订单
          </button>
          <button
            className="danger-button"
            disabled={disabled}
            onClick={() => onDecision('approve')}
          >
            确认取消订单
          </button>
        </div>
      </footer>
    </section>
  );
}
