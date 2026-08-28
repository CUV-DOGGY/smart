import { useEffect } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';

import { OrderAttemptContext } from './OrderAttemptContext.js';
import { OrderErrorNotice } from './components/OrderErrorNotice.jsx';
import { OrderUnknownNotice } from './components/OrderUnknownNotice.jsx';
import { useOrderAttempt } from './useOrderAttempt.js';

export function OrderCenterLayout() {
  const navigate = useNavigate();
  const orderAttempt = useOrderAttempt();
  const {
    succeededOrder,
    pendingAttempt,
    isSubmitting,
    progress,
    failure,
    unknownMessage,
    isUnknownNoticeOpen,
    continuePendingOrder,
    dismissUnknownNotice,
    clearSucceededOrder,
  } = orderAttempt;

  useEffect(() => {
    if (!succeededOrder?.order_id) return;
    const order = succeededOrder;
    clearSucceededOrder();
    navigate('/orders/history', {
      replace: true,
      state: {
        notice: `订单 ${order.order_id} 创建成功，总计 ¥${Number(order.total_price || 0).toFixed(2)}`,
      },
    });
  }, [clearSucceededOrder, navigate, succeededOrder]);

  const exitUnknownOrder = () => {
    // 只退出确认界面；pendingAttempt 及 localStorage 记录必须继续保留。
    dismissUnknownNotice();
    navigate('/orders/shops');
  };

  return (
    <OrderAttemptContext.Provider value={orderAttempt}>
      {isSubmitting && progress && (
        <div className="order-global-alert alert warning">{progress}</div>
      )}
      {pendingAttempt && !isSubmitting && !isUnknownNoticeOpen && (
        <div className="order-global-alert alert warning">
          <span>有一笔订单结果尚未确认，请勿重复下单。</span>
          <button type="button" onClick={continuePendingOrder}>
            继续确认
          </button>
        </div>
      )}
      <Outlet />
      {failure && <OrderErrorNotice error={failure} />}
      {isUnknownNoticeOpen && (
        <OrderUnknownNotice
          message={unknownMessage}
          isSubmitting={isSubmitting}
          onRetry={continuePendingOrder}
          onExit={exitUnknownOrder}
        />
      )}
    </OrderAttemptContext.Provider>
  );
}
