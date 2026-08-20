import { useEffect, useMemo, useRef, useState } from 'react';

import { addressApi } from '../address/api.js';
import { orderApi } from './api.js';

const STATUS_LABELS = {
  pending_payment: '待支付', paid: '已支付', preparing: '备餐中', delivering: '配送中',
  completed: '已完成', canceling: '取消中', canceled: '已取消', refunded: '已退款',
};

export function OrderPage() {
  const [shops, setShops] = useState([]);
  const [products, setProducts] = useState([]);
  const [addresses, setAddresses] = useState([]);
  const [orders, setOrders] = useState([]);
  const [shopId, setShopId] = useState('');
  const [addressId, setAddressId] = useState('');
  const [quantities, setQuantities] = useState({});
  const [detail, setDetail] = useState(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const idempotencyRef = useRef({ fingerprint: '', key: '' });

  const loadOrders = async () => {
    const response = await orderApi.list();
    setOrders(response.items);
  };
  useEffect(() => {
    Promise.all([orderApi.listShops(), addressApi.list(), orderApi.list()]).then(
      ([shopResponse, addressResponse, orderResponse]) => {
        setShops(shopResponse.items);
        setAddresses(addressResponse.items);
        setOrders(orderResponse.items);
        setShopId(shopResponse.items[0]?.shop_id || '');
        setAddressId(addressResponse.items.find((item) => item.is_default)?.address_id || addressResponse.items[0]?.address_id || '');
      },
      (requestError) => setError(requestError.message),
    );
  }, []);
  useEffect(() => {
    if (!shopId) { setProducts([]); return; }
    orderApi.listProducts(shopId).then(
      (response) => { setProducts(response.items); setQuantities({}); },
      (requestError) => setError(requestError.message),
    );
  }, [shopId]);

  const selectedItems = useMemo(() => products.filter((item) => quantities[item.food_id] > 0).map((item) => ({ ...item, quantity: quantities[item.food_id] })), [products, quantities]);
  const goodsTotal = selectedItems.reduce((total, item) => total + item.price * item.quantity, 0);
  const selectedShop = shops.find((shop) => shop.shop_id === shopId);

  const changeQuantity = (foodId, delta, stock) => {
    setQuantities((current) => ({ ...current, [foodId]: Math.max(0, Math.min(stock, (current[foodId] || 0) + delta)) }));
  };

  const createOrder = async () => {
    if (!addressId || !selectedItems.length) { setError('请选择收货地址和至少一件商品'); return; }
    const payload = { shop_id: shopId, address_id: addressId, items: selectedItems.map(({ food_id, quantity }) => ({ food_id, quantity })) };
    const fingerprint = JSON.stringify(payload);
    if (idempotencyRef.current.fingerprint !== fingerprint) {
      idempotencyRef.current = { fingerprint, key: `web-${crypto.randomUUID()}` };
    }
    setSubmitting(true);
    setError('');
    setNotice('');
    try {
      const result = await orderApi.create(payload, idempotencyRef.current.key);
      setNotice(`订单 ${result.order_id} 创建成功，总计 ¥${result.total_price.toFixed(2)}`);
      idempotencyRef.current = { fingerprint: '', key: '' };
      setQuantities({});
      await loadOrders();
      const refreshed = await orderApi.listProducts(shopId);
      setProducts(refreshed.items);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  };

  const showDetail = async (id) => {
    try { setDetail(await orderApi.get(id)); } catch (requestError) { setError(requestError.message); }
  };
  const cancelOrder = async (id) => {
    if (!window.confirm('确定取消这个订单吗？')) return;
    try { await orderApi.cancel(id); await loadOrders(); if (detail?.order_id === id) setDetail(await orderApi.get(id)); } catch (requestError) { setError(requestError.message); }
  };

  return (
    <section className="page">
      <header className="page-header"><div><p className="eyebrow">ORDER CENTER</p><h1>订单中心</h1><p>选品下单、查询进度并管理取消请求</p></div></header>
      {error && <div className="alert error">{error}</div>}{notice && <div className="alert success">{notice}</div>}
      <div className="order-layout">
        <section className="panel checkout-panel">
          <div className="panel-title"><div><h2>创建订单</h2><p>库存与价格由服务端最终确认</p></div></div>
          {!shops.length ? <div className="empty-state"><h3>目录尚未准备</h3><p>请先按 README 数据契约向 MongoDB 的 <code>shops</code> 和 <code>products</code> 集合写入数据。</p></div> : <>
            <div className="form-grid two"><label>店铺<select value={shopId} onChange={(event) => setShopId(event.target.value)}>{shops.map((shop) => <option key={shop.shop_id} value={shop.shop_id}>{shop.shop_name}</option>)}</select></label><label>收货地址<select value={addressId} onChange={(event) => setAddressId(event.target.value)}><option value="">请选择</option>{addresses.map((address) => <option key={address.address_id} value={address.address_id}>{address.receiver_name} · {address.detail_address}</option>)}</select></label></div>
            {!addresses.length && <div className="alert warning">请先到“收货地址”页面新增地址。</div>}
            <div className="product-list">{products.map((product) => <article key={product.food_id}><div><strong>{product.food_name}</strong><small>库存 {product.stock}</small></div><span>¥{product.price.toFixed(2)}</span><div className="quantity"><button onClick={() => changeQuantity(product.food_id, -1, product.stock)}>−</button><b>{quantities[product.food_id] || 0}</b><button onClick={() => changeQuantity(product.food_id, 1, product.stock)}>＋</button></div></article>)}</div>
            {!products.length && <div className="empty-state compact">该店铺暂无可售商品</div>}
            <div className="checkout-summary"><div><span>商品金额</span><strong>¥{goodsTotal.toFixed(2)}</strong></div><div><span>配送费</span><strong>¥{(selectedShop?.delivery_fee || 0).toFixed(2)}</strong></div><div className="total"><span>预计合计</span><strong>¥{(goodsTotal + (selectedShop?.delivery_fee || 0)).toFixed(2)}</strong></div><button className="primary full" disabled={submitting || !selectedItems.length || !addressId} onClick={createOrder}>{submitting ? '提交中…' : '提交订单'}</button></div>
          </>}
        </section>
        <section className="panel history-panel"><div className="panel-title"><div><h2>历史订单</h2><p>共 {orders.length} 条</p></div></div><div className="order-list">{orders.map((order) => <article key={order.order_id} onClick={() => showDetail(order.order_id)}><div><strong>{order.items.map((item) => `${item.food_name} ×${item.quantity}`).join('、')}</strong><small>{new Date(order.create_time).toLocaleString()} · {order.shop_id}</small></div><div><span className="badge">{STATUS_LABELS[order.order_status] || order.order_status}</span><strong>¥{order.total_price.toFixed(2)}</strong></div></article>)}{!orders.length && <div className="empty-state compact">还没有订单</div>}</div></section>
      </div>
      {detail && <OrderDetail order={detail} onClose={() => setDetail(null)} onCancel={cancelOrder} />}
    </section>
  );
}

function OrderDetail({ order, onClose, onCancel }) {
  const cancellable = ['pending_payment', 'paid', 'preparing'].includes(order.order_status);
  return <div className="modal-backdrop"><section className="modal order-modal"><header><div><p className="eyebrow">ORDER DETAIL</p><h2>订单详情</h2></div><button className="icon-button" onClick={onClose}>×</button></header><dl><dt>订单号</dt><dd>{order.order_id}</dd><dt>状态</dt><dd>{STATUS_LABELS[order.order_status] || order.order_status}</dd><dt>店铺</dt><dd>{order.shop_id}</dd><dt>商品</dt><dd>{order.items.map((item) => `${item.food_name} ×${item.quantity}`).join('、')}</dd><dt>总金额</dt><dd>¥{order.total_price.toFixed(2)}</dd></dl><footer>{cancellable && <button className="danger-button" onClick={() => onCancel(order.order_id)}>取消订单</button>}<button className="primary" onClick={onClose}>关闭</button></footer></section></div>;
}
