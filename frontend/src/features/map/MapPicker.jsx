import { Component, useEffect, useRef, useState } from 'react';

import { AmapPickerAdapter, amapError } from './amapAdapter.js';

export function MapPicker(props) {
  return (
    <MapErrorBoundary onClose={props.onClose}>
      <MapPickerContent {...props} />
    </MapErrorBoundary>
  );
}

function MapPickerContent({ initialValue, onConfirm, onClose }) {
  const containerRef = useRef(null);
  const adapterRef = useRef(null);
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState(initialValue?.formatted_address || '');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const adapter = new AmapPickerAdapter(
      (location) => active && setSelected(location),
      (adapterError) => active && setError(adapterError.message),
    );
    adapterRef.current = adapter;
    const coordinates = initialValue?.longitude != null ? [initialValue.longitude, initialValue.latitude] : null;
    adapter.mount(containerRef.current, coordinates).catch((mountError) => {
      if (active) setError(amapError(mountError, '地图组件加载失败').message);
    }).finally(() => active && setLoading(false));
    return () => {
      active = false;
      adapter.destroy();
      adapterRef.current = null;
    };
  }, [initialValue]);

  const search = async (event) => {
    event.preventDefault();
    if (!query.trim()) return;
    setError('');
    try {
      await adapterRef.current.search(query.trim());
    } catch (searchError) {
      setError(amapError(searchError, '地图搜索失败，请稍后重试').message);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="地图选点">
      <section className="modal map-modal">
        <header><div><p className="eyebrow">AMAP PICKER</p><h2>确认收货位置</h2></div><button className="icon-button" onClick={onClose}>×</button></header>
        <form className="map-search" onSubmit={search}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索小区、写字楼或道路" /><button className="secondary">搜索</button></form>
        <div className="map-stage">
          <div className="map-container" ref={containerRef} />
          {loading && <div className="map-loading">地图加载中…</div>}
        </div>
        {error && <div className="alert error">{error}</div>}
        <div className="map-selection"><strong>{selected ? selected.formatted_address : '请点击地图或拖动标记'}</strong>{selected && <small>{selected.longitude.toFixed(6)}, {selected.latitude.toFixed(6)}</small>}</div>
        <footer><button className="secondary" onClick={onClose}>取消</button><button className="primary" disabled={!selected} onClick={() => onConfirm(selected)}>使用此位置</button></footer>
      </section>
    </div>
  );
}

class MapErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.error('Map picker render failed', error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="地图选点异常">
        <section className="modal map-modal">
          <header><div><p className="eyebrow">AMAP PICKER</p><h2>地图组件加载失败</h2></div></header>
          <div className="alert error map-fallback">请关闭后重试，并检查高德 JSAPI Key、安全密钥及域名白名单。</div>
          <footer><button type="button" className="secondary" onClick={this.props.onClose}>关闭</button></footer>
        </section>
      </div>
    );
  }
}
