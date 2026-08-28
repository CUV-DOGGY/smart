import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { orderApi } from './api.js';
import { HistoryOrderDetail } from './components/HistoryOrderDetail.jsx';
import { OrderHistoryItem } from './components/OrderHistoryItem.jsx';

export function OrderHistoryPage() {
  const location = useLocation();
  const [orders, setOrders] = useState([]);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadOrders = useCallback(async () => {
    try {
      const response = await orderApi.list();
      setOrders(response.items);
      setError('');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOrders();
  }, [loadOrders]);

  const showDetail = async (orderId) => {
    try {
      setDetail(await orderApi.get(orderId));
      setError('');
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const cancelOrder = async (orderId) => {
    if (!window.confirm('确定取消这个订单吗？')) return;
    try {
      await orderApi.cancel(orderId);
      await loadOrders();
      if (detail?.order_id === orderId) {
        setDetail(await orderApi.get(orderId));
      }
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  return (
    <section className="page history-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">ORDER HISTORY</p>
          <h1>历史订单</h1>
          <p>共 {orders.length} 条</p>
        </div>
        <Link className="secondary page-action-link" to="/orders/shops">
          继续点餐
        </Link>
      </header>
      {location.state?.notice && (
        <div className="alert success">{location.state.notice}</div>
      )}
      {error && <div className="alert error">{error}</div>}
      {loading ? (
        <div className="empty-state">正在加载历史订单…</div>
      ) : (
        <section className="panel history-panel">
          <div className="order-list">
            {orders.map((order) => (
              <OrderHistoryItem
                key={order.order_id}
                order={order}
                onSelect={showDetail}
              />
            ))}
            {!orders.length && (
              <div className="empty-state compact">还没有订单</div>
            )}
          </div>
        </section>
      )}
      {detail && (
        <HistoryOrderDetail
          order={detail}
          onClose={() => setDetail(null)}
          onCancel={cancelOrder}
        />
      )}
    </section>
  );
}
