import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { addressApi } from '../address/api.js';
import { orderApi } from './api.js';
import {
  buildOrderPayload,
  cartGoodsTotal,
  cartQuantity,
  changeCartQuantity,
} from './cart.js';
import { Cart } from './components/Cart.jsx';
import { CheckoutOrderDetail } from './components/CheckoutOrderDetail.jsx';
import { ProductItem } from './components/ProductItem.jsx';
import { ShopDetail } from './components/ShopDetail.jsx';
import { useOrderAttemptContext } from './OrderAttemptContext.js';

export function ProductDetailPage() {
  const { shopId = '' } = useParams();
  const {
    pendingAttempt,
    isSubmitting,
    failure,
    submitOrder,
  } = useOrderAttemptContext();
  const [shop, setShop] = useState(null);
  const [products, setProducts] = useState([]);
  const [addresses, setAddresses] = useState([]);
  const [addressId, setAddressId] = useState('');
  const [cartList, setCartList] = useState([]);
  const [isCartExpanded, setIsCartExpanded] = useState(false);
  const [isOrderDetailOpen, setIsOrderDetailOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [validationError, setValidationError] = useState('');
  // 明确失败时详情暂时隐藏；错误提示消失后恢复用户原来的确认内容。
  const restoreDetailAfterFailureRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setCartList([]);
    setIsCartExpanded(false);
    setIsOrderDetailOpen(false);

    Promise.all([
      orderApi.getShop(shopId, { signal: controller.signal }),
      orderApi.listProducts(shopId, { signal: controller.signal }),
      addressApi.list({ signal: controller.signal }),
    ]).then(
      ([shopResponse, productResponse, addressResponse]) => {
        setShop(shopResponse);
        setProducts(productResponse.items);
        setAddresses(addressResponse.items);
        setAddressId(
          addressResponse.items.find((item) => item.is_default)?.address_id ||
            addressResponse.items[0]?.address_id ||
            '',
        );
        setLoading(false);
      },
      (requestError) => {
        if (requestError.code === 'REQUEST_ABORTED') return;
        setError(requestError.message);
        setLoading(false);
      },
    );

    return () => controller.abort();
  }, [shopId]);

  useEffect(() => {
    if (failure) {
      setIsOrderDetailOpen((currentlyOpen) => {
        if (currentlyOpen) restoreDetailAfterFailureRef.current = true;
        return false;
      });
      return;
    }
    if (restoreDetailAfterFailureRef.current) {
      restoreDetailAfterFailureRef.current = false;
      setIsOrderDetailOpen(true);
    }
  }, [failure]);

  // 待确认订单存在时锁定购物车，避免界面内容偏离已持久化的请求。
  const checkoutLocked = isSubmitting || Boolean(pendingAttempt);

  const updateCart = (product, delta) => {
    if (checkoutLocked) return;
    setValidationError('');
    setCartList((current) => changeCartQuantity(current, product, delta));
  };

  const openOrderDetail = () => {
    setValidationError('');
    setIsOrderDetailOpen(true);
  };

  const toggleCart = () => {
    if (!cartList.length) return;
    setIsCartExpanded((current) => !current);
  };

  /** 校验页面数据后，将可信字段组成订单请求交给幂等提交状态机。 */
  const createOrder = async () => {
    if (!shop?.is_accepting_orders) {
      setValidationError('店铺当前暂停接单');
      return;
    }
    if (!addressId || !cartList.length) {
      setValidationError('请选择收货地址和至少一件商品');
      return;
    }
    if (cartList.length > 50) {
      setValidationError('一笔订单最多只能包含 50 种商品');
      return;
    }
    if (cartGoodsTotal(cartList) < shop.minimum_order_amount) {
      setValidationError('当前商品金额未达到最低起送金额');
      return;
    }

    setValidationError('');
    const result = await submitOrder(
      buildOrderPayload({ shopId, addressId, cartList }),
    );
    if (result.status === 'blocked' && result.error?.message) {
      setValidationError(result.error.message);
    }
  };

  if (loading) {
    return <div className="page empty-state">正在加载店铺和商品…</div>;
  }

  if (error || !shop) {
    return (
      <section className="page">
        <div className="alert error">{error || '店铺不存在'}</div>
        <Link to="/orders/shops">返回店铺列表</Link>
      </section>
    );
  }

  return (
    <section className="page product-detail-page">
      <header className="page-header compact-header">
        <Link to="/orders/shops">← 返回店铺列表</Link>
        <Link to="/orders/history">历史订单</Link>
      </header>
      <ShopDetail shop={shop} />
      {!shop.is_accepting_orders && (
        <div className="alert warning">店铺当前暂停接单，可以浏览商品但无法购买。</div>
      )}

      <section className="panel products-panel">
        <div className="panel-title">
          <div>
            <h2>商品列表</h2>
            <p>选择需要购买的商品数量</p>
          </div>
        </div>
        <div className="product-list">
          {products.map((product) => (
            <ProductItem
              key={product.food_id}
              product={product}
              quantity={cartQuantity(cartList, product.food_id)}
              disabled={checkoutLocked || !shop.is_accepting_orders}
              onChange={updateCart}
            />
          ))}
        </div>
        {!products.length && (
          <div className="empty-state compact">该店铺暂无可售商品</div>
        )}
      </section>

      <Cart
        cartList={cartList}
        expanded={isCartExpanded}
        purchaseDisabled={checkoutLocked || !shop.is_accepting_orders}
        onToggle={toggleCart}
        onPurchase={openOrderDetail}
      />

      {isOrderDetailOpen && (
        <CheckoutOrderDetail
          shop={shop}
          cartList={cartList}
          addresses={addresses}
          addressId={addressId}
          validationError={validationError}
          isSubmitting={isSubmitting}
          onAddressChange={setAddressId}
          onClose={() => setIsOrderDetailOpen(false)}
          onSubmit={createOrder}
        />
      )}
    </section>
  );
}
