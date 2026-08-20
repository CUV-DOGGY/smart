import { Navigate, Route, Routes } from 'react-router-dom';

import { AddressPage } from '../features/address/AddressPage.jsx';
import { LoginPage } from '../features/auth/LoginPage.jsx';
import { ProtectedRoute } from '../features/auth/ProtectedRoute.jsx';
import { RegisterPage } from '../features/auth/RegisterPage.jsx';
import { ChatPage } from '../features/chat/ChatPage.jsx';
import { OrderPage } from '../features/order/OrderPage.jsx';
import { AppShell } from '../shared/ui/AppShell.jsx';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<ProtectedRoute><AppShell /></ProtectedRoute>}>
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/addresses" element={<AddressPage />} />
        <Route path="/orders" element={<OrderPage />} />
      </Route>
      <Route path="/" element={<Navigate to="/chat" replace />} />
      <Route path="*" element={<div className="screen-center"><h1>404</h1><p>页面不存在</p></div>} />
    </Routes>
  );
}
