const moneyFormatter = new Intl.NumberFormat('zh-CN', {
  style: 'currency',
  currency: 'CNY',
  minimumFractionDigits: 2,
});


function formatMoney(value) {
  return moneyFormatter.format(Number(value) || 0);
}


export function OrderConfirmationCard({ confirmation, disabled, onDecision }) {
  const order = confirmation.presentation;

  return (
    <section className="confirmation-card order-confirmation-card" aria-label="待确认订单">
      <header className="order-confirmation-header">
        <div className="order-confirmation-icon" aria-hidden="true">✓</div>
        <div>
          <p className="eyebrow">ORDER CONFIRMATION</p>
          <h2>请确认订单信息</h2>
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
                  <td><strong>{formatMoney(item.line_total)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="order-confirmation-meta">
          <div className="order-delivery-info">
            <span className="order-confirmation-label">配送至</span>
            <strong>{order.receiver_name} · {order.receiver_phone}</strong>
            <p>{order.delivery_address}</p>
          </div>
          <dl className="order-confirmation-totals">
            <div><dt>商品金额</dt><dd>{formatMoney(order.goods_amount)}</dd></div>
            <div><dt>配送费</dt><dd>{formatMoney(order.delivery_fee)}</dd></div>
            <div className="grand-total"><dt>应付合计</dt><dd>{formatMoney(order.total_price)}</dd></div>
          </dl>
        </div>
      </div>

      <footer className="order-confirmation-footer">
        <p>点击确认后才会创建订单，并再次校验库存、价格和配送范围。</p>
        <div className="confirmation-actions">
          <button className="secondary" disabled={disabled} onClick={() => onDecision('reject')}>取消下单</button>
          <button className="primary" disabled={disabled} onClick={() => onDecision('approve')}>
            确认下单 · {formatMoney(order.total_price)}
          </button>
        </div>
      </footer>
    </section>
  );
}
