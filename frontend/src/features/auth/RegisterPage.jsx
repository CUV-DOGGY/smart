import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { authApi } from './api.js';

export function RegisterPage() {
  const [form, setForm] = useState({ username: '', password: '', confirm: '' });
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  const submit = async (event) => {
    event.preventDefault();
    if (form.password !== form.confirm) {
      setError('两次输入的密码不一致');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      await authApi.register({
        username: form.username,
        password: form.password,
      });
      navigate('/login', { replace: true });
    } catch (requestError) {
      setError(requestError.message || '注册失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="brand-mark">S</div>
        <p className="eyebrow">CREATE ACCOUNT</p>
        <h1>创建账号</h1>
        <form onSubmit={submit} className="stack-form">
          <label>
            用户名
            <input
              required
              minLength="3"
              maxLength="32"
              autoComplete="username"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
            />
          </label>
          <label>
            密码
            <input
              required
              minLength="8"
              maxLength="128"
              type="password"
              autoComplete="new-password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
          </label>
          <label>
            确认密码
            <input
              required
              type="password"
              autoComplete="new-password"
              value={form.confirm}
              onChange={(e) => setForm({ ...form, confirm: e.target.value })}
            />
          </label>
          {error && <div className="alert error">{error}</div>}
          <button className="primary" disabled={submitting}>
            {submitting ? '注册中…' : '注册'}
          </button>
        </form>
        <p className="auth-link">
          已有账号？<Link to="/login">返回登录</Link>
        </p>
      </section>
    </main>
  );
}
