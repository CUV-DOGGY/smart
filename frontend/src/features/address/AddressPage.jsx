import { useCallback, useEffect, useState } from 'react';

import { addressApi } from './api.js';
import { AddressForm } from './AddressForm.jsx';

export function AddressPage() {
  const [addresses, setAddresses] = useState([]);
  const [editing, setEditing] = useState(undefined);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const response = await addressApi.list();
      setAddresses(response.items);
      setError('');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (payload) => {
    if (editing?.address_id) await addressApi.update(editing.address_id, payload);
    else await addressApi.create(payload);
    setEditing(undefined);
    await load();
  };

  const setDefault = async (id) => {
    try { await addressApi.setDefault(id); await load(); } catch (requestError) { setError(requestError.message); }
  };
  const remove = async (id) => {
    if (!window.confirm('确定删除这个地址吗？')) return;
    try { await addressApi.remove(id); await load(); } catch (requestError) { setError(requestError.message); }
  };

  return (
    <section className="page">
      <header className="page-header"><div><p className="eyebrow">DELIVERY ADDRESSES</p><h1>收货地址</h1><p>管理用于订单配送与范围校验的位置</p></div><button className="primary" onClick={() => setEditing(null)}>＋ 新增地址</button></header>
      {error && <div className="alert error">{error}</div>}
      {editing !== undefined && <AddressForm key={editing?.address_id || 'new'} initialValue={editing || null} onSubmit={save} onCancel={() => setEditing(undefined)} />}
      {loading ? <div className="empty-state">加载地址中…</div> : (
        <div className="card-grid">
          {addresses.map((address) => (
            <article className={`address-card ${address.is_default ? 'default' : ''}`} key={address.address_id}>
              <div className="card-top"><div><strong>{address.receiver_name}</strong><span>{address.receiver_phone}</span></div>{address.is_default && <span className="badge">默认</span>}</div>
              <p>{address.province}{address.city !== address.province && address.city}{address.district}{address.detail_address}</p>
              <small>{address.verification_status === 'verified' ? '✓ 已验证位置' : '△ 地图位置待验证'}</small>
              <footer><button className="ghost" onClick={() => setEditing(address)}>编辑</button>{!address.is_default && <button className="ghost" onClick={() => setDefault(address.address_id)}>设为默认</button>}<button className="ghost danger" onClick={() => remove(address.address_id)}>删除</button></footer>
            </article>
          ))}
          {!addresses.length && <div className="empty-state"><h2>还没有收货地址</h2><p>新增地址后即可创建配送订单。</p></div>}
        </div>
      )}
    </section>
  );
}
