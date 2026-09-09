import { NavLink, Outlet } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';

import { anonymous } from '../../features/auth/authSlice.js';
import { tokenStorage } from '../storage/tokenStorage.js';

export function AppShell() {
  const user = useSelector((state) => state.auth.user);
  const dispatch = useDispatch();
  const logout = () => {
    tokenStorage.clear();
    dispatch(anonymous());
  };

  return (
    <div className="app-shell">
      <aside className="app-nav">
        <div className="brand">
          <span className="brand-mark small">S</span>
          <div>
            <strong>SmartServe</strong>
            <small>AI 客服工作台</small>
          </div>
        </div>
        <nav>
          <NavLink to="/chat">💬 智能客服</NavLink>
          <NavLink to="/addresses">⌖ 收货地址</NavLink>
          <NavLink to="/orders/shops">▤ 店铺点餐</NavLink>
          <NavLink to="/orders/history">◷ 历史订单</NavLink>
        </nav>
        <div className="nav-user">
          <span className="avatar">
            {user?.username?.slice(0, 1).toUpperCase()}
          </span>
          <div>
            <strong>{user?.username}</strong>
            <small>已安全登录</small>
          </div>
          <button className="ghost" onClick={logout}>
            退出
          </button>
        </div>
      </aside>
      <main className="app-content">
        <Outlet />
      </main>
    </div>
  );
}
