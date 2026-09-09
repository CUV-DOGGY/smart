import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { orderApi } from './api.js';
import { ShopItem } from './components/ShopItem.jsx';

export function ShopListPage() {
  const navigate = useNavigate();
  const [shopList, setShopList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    orderApi.listShops({ signal: controller.signal }).then(
      (response) => {
        setShopList(response.items);
        setError('');
        setLoading(false);
      },
      (requestError) => {
        if (requestError.code === 'REQUEST_ABORTED') return;
        setError(requestError.message);
        setLoading(false);
      },
    );
    return () => controller.abort();
  }, []);

  const selectShop = (shopId) => {
    navigate(`/orders/shops/${encodeURIComponent(shopId)}`);
  };

  return (
    <section className="page shop-list-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">SHOP DIRECTORY</p>
          <h1>选择店铺</h1>
          <p>查看店铺信息后进入商品页面点餐</p>
        </div>
        <Link className="secondary page-action-link" to="/orders/history">
          历史订单
        </Link>
      </header>
      {error && <div className="alert error">{error}</div>}
      {loading ? (
        <div className="empty-state">正在加载店铺…</div>
      ) : (
        <div className="shop-list">
          {shopList.map((shop) => (
            <ShopItem key={shop.shop_id} shop={shop} onSelect={selectShop} />
          ))}
          {!shopList.length && (
            <div className="empty-state">
              <h2>暂无可展示店铺</h2>
              <p>请稍后刷新页面重试。</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
