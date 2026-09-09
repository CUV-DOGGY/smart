import { Navigate, Route, Routes } from 'react-router-dom';

import { AddressPage } from '../features/address/AddressPage.jsx';
import { LoginPage } from '../features/auth/LoginPage.jsx';
import { ProtectedRoute } from '../features/auth/ProtectedRoute.jsx';
import { RegisterPage } from '../features/auth/RegisterPage.jsx';
import { ChatPage } from '../features/chat/ChatPage.jsx';
import { OrderCenterLayout } from '../features/order/OrderCenterLayout.jsx';
import { OrderHistoryPage } from '../features/order/OrderHistoryPage.jsx';
import { ProductDetailPage } from '../features/order/ProductDetailPage.jsx';
import { ShopListPage } from '../features/order/ShopListPage.jsx';
import { AppShell } from '../shared/ui/AppShell.jsx';
import { FeatureErrorBoundary } from '../shared/ui/FeatureErrorBoundary.jsx';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route
          path="/chat"
          element={
            <FeatureErrorBoundary
              title="聊天页面暂时无法显示"
              message="会话数据或流式响应出现异常，请重新加载此页面。"
            >
              <ChatPage />
            </FeatureErrorBoundary>
          }
        />
        <Route path="/addresses" element={<AddressPage />} />
        <Route path="/orders" element={<OrderCenterLayout />}>
          <Route index element={<Navigate to="shops" replace />} />
          <Route path="shops" element={<ShopListPage />} />
          <Route path="shops/:shopId" element={<ProductDetailPage />} />
          <Route path="history" element={<OrderHistoryPage />} />
        </Route>
      </Route>
      <Route path="/" element={<Navigate to="/chat" replace />} />
      <Route
        path="*"
        element={
          <div className="screen-center">
            <h1>404</h1>
            <p>页面不存在</p>
          </div>
        }
      />
    </Routes>
  );
}
