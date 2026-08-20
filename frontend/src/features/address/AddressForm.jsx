import { useState } from 'react';

import { MapPicker } from '../map/MapPicker.jsx';

const EMPTY = {
  receiver_name: '', receiver_phone: '', province: '', city: '', district: '',
  detail_address: '', longitude: null, latitude: null, formatted_address: '',
};

export function AddressForm({ initialValue, onSubmit, onCancel }) {
  const [form, setForm] = useState(() => ({ ...EMPTY, ...initialValue }));
  const [showMap, setShowMap] = useState(false);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const change = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    const payload = {
      receiver_name: form.receiver_name.trim(),
      receiver_phone: form.receiver_phone.trim(),
      province: form.province.trim(),
      city: form.city.trim(),
      district: form.district.trim(),
      detail_address: form.detail_address.trim(),
      ...(form.longitude != null ? { longitude: form.longitude, latitude: form.latitude } : {}),
    };
    try {
      await onSubmit(payload);
    } catch (requestError) {
      setError(requestError.message || '地址保存失败');
      if (requestError.code === 'ADDRESS_NEEDS_MAP_PICK') setShowMap(true);
    } finally {
      setSaving(false);
    }
  };

  const acceptMap = (location) => {
    setForm({ ...form, ...location });
    setShowMap(false);
    setError('');
  };

  return (
    <>
      <form className="panel stack-form address-form" onSubmit={submit}>
        <div className="panel-title"><div><h2>{initialValue ? '编辑地址' : '新增地址'}</h2><p>文字无法精确定位时请使用地图选点</p></div><button type="button" className="icon-button" onClick={onCancel}>×</button></div>
        <div className="form-grid two"><label>收货人<input required maxLength="50" value={form.receiver_name} onChange={change('receiver_name')} /></label><label>手机号<input required pattern="1[3-9][0-9]{9}" value={form.receiver_phone} onChange={change('receiver_phone')} /></label></div>
        <div className="form-grid three"><label>省<input required maxLength="64" value={form.province} onChange={change('province')} /></label><label>市<input required maxLength="64" value={form.city} onChange={change('city')} /></label><label>区/县<input required maxLength="64" value={form.district} onChange={change('district')} /></label></div>
        <label>详细地址<textarea required maxLength="300" rows="3" value={form.detail_address} onChange={change('detail_address')} /></label>
        <button type="button" className="map-pick-button" onClick={() => setShowMap(true)}>⌖ {form.longitude != null ? `已选点 ${form.longitude.toFixed(5)}, ${form.latitude.toFixed(5)}` : '打开高德地图选点'}</button>
        {error && <div className="alert error">{error}</div>}
        <div className="form-actions"><button type="button" className="secondary" onClick={onCancel}>取消</button><button className="primary" disabled={saving}>{saving ? '保存中…' : '保存地址'}</button></div>
      </form>
      {showMap && <MapPicker initialValue={form} onConfirm={acceptMap} onClose={() => setShowMap(false)} />}
    </>
  );
}
