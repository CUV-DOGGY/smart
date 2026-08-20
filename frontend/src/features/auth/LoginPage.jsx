import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';

import { tokenStorage } from '../../shared/storage/tokenStorage.js';
import { authApi } from './api.js';
import { authenticated } from './authSlice.js';

export function LoginPage() {
  const [form, setForm] = useState({ username: '', password: '' });
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const status = useSelector((state) => state.auth.status);
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  if (status === 'authenticated') return <Navigate to="/chat" replace />;

  const submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      const token = await authApi.login(form.username, form.password);
      tokenStorage.set(token.access_token);
      const user = await authApi.me();
      dispatch(authenticated(user));
      const target = location.state?.from?.startsWith('/') ? location.state.from : '/chat';
      navigate(target, { replace: true });
    } catch (requestError) {
      tokenStorage.clear();
      setError(requestError.message || '登录失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="brand-mark">S</div>
        <p className="eyebrow">SMARTSERVE AI</p>
        <h1>欢迎回来</h1>
        <p className="muted">登录后管理客服会话、地址与订单</p>
        <form onSubmit={submit} className="stack-form">
          <label>用户名<input required minLength="3" maxLength="32" autoComplete="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
          <label>密码<input required minLength="8" maxLength="128" type="password" autoComplete="current-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
          {error && <div className="alert error">{error}</div>}
          <button className="primary" disabled={submitting}>{submitting ? '登录中…' : '登录'}</button>
        </form>
        <p className="auth-link">还没有账号？<Link to="/register">立即注册</Link></p>
      </section>
    </main>
  );
}
