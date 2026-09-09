import AMapLoader from '@amap/amap-jsapi-loader';

import { env } from '../../shared/config/env.js';

let loaderPromise = null;

async function loadAmap() {
  const isConfigured = (value) => value && !value.startsWith('replace-with-');
  if (!isConfigured(env.amapKey) || !isConfigured(env.amapSecurityCode)) {
    throw new Error('未配置高德 Web 端 JSAPI Key 与安全密钥');
  }
  window._AMapSecurityConfig = { securityJsCode: env.amapSecurityCode };
  loaderPromise ||= AMapLoader.load({
    key: env.amapKey,
    version: '2.0',
    plugins: ['AMap.Geocoder', 'AMap.ToolBar'],
  }).catch((error) => {
    loaderPromise = null;
    throw amapError(
      error,
      '高德地图加载失败，请检查 JSAPI Key、安全密钥和域名白名单',
    );
  });
  return loaderPromise;
}

export class AmapPickerAdapter {
  constructor(onLocation, onError = () => {}) {
    this.onLocation = onLocation;
    this.onError = onError;
    this.map = null;
    this.marker = null;
    this.geocoder = null;
    this.AMap = null;
    this.disposed = false;
  }

  async mount(container, initialLocation) {
    this.AMap = await loadAmap();
    if (this.disposed || !container?.isConnected) return;
    const center = initialLocation || [116.397428, 39.90923];
    this.map = new this.AMap.Map(container, {
      zoom: initialLocation ? 16 : 11,
      center,
    });
    this.map.addControl(new this.AMap.ToolBar({ position: 'RT' }));
    this.geocoder = new this.AMap.Geocoder();
    this.marker = new this.AMap.Marker({ position: center, draggable: true });
    this.map.add(this.marker);
    this.map.on('click', (event) => this._pickSafely(event.lnglat));
    this.marker.on('dragend', (event) => this._pickSafely(event.lnglat));
    if (initialLocation) await this.pick(initialLocation);
  }

  async search(address) {
    const result = await this._geocoderCall('getLocation', address);
    const location = result.geocodes?.[0]?.location;
    if (!location) throw new Error('没有找到匹配的位置');
    this.map.setZoomAndCenter(16, location);
    await this.pick(location);
  }

  async pick(location) {
    this.marker.setPosition(location);
    const result = await this._geocoderCall('getAddress', location);
    const regeocode = result.regeocode;
    if (!regeocode) throw new Error('无法解析该位置');
    const component = regeocode.addressComponent || {};
    const province = text(component.province);
    const city = text(component.city) || province;
    const district = text(component.district);
    const formatted = text(regeocode.formattedAddress);
    const detail = formatted
      .replace(province, '')
      .replace(city === province ? '' : city, '')
      .replace(district, '')
      .trim();
    const lng =
      typeof location.getLng === 'function'
        ? location.getLng()
        : Number(location[0]);
    const lat =
      typeof location.getLat === 'function'
        ? location.getLat()
        : Number(location[1]);
    this.onLocation({
      longitude: lng,
      latitude: lat,
      province,
      city,
      district,
      detail_address: detail || formatted,
      formatted_address: formatted,
    });
  }

  destroy() {
    this.disposed = true;
    this.map?.destroy();
    this.map = null;
    this.marker = null;
    this.geocoder = null;
  }

  _pickSafely(location) {
    void this.pick(location).catch((error) => {
      this.onError(amapError(error, '高德地址解析失败，请重新选择'));
    });
  }

  _geocoderCall(method, value) {
    return new Promise((resolve, reject) => {
      this.geocoder[method](value, (status, result) => {
        if (status === 'complete' && result?.info === 'OK') resolve(result);
        else reject(amapError(result, '高德地址解析失败，请重新选择'));
      });
    });
  }
}

export function amapError(error, fallback) {
  if (error instanceof Error && error.message) return error;
  if (typeof error === 'string' && error.trim()) return new Error(error.trim());
  const message =
    error && typeof error === 'object'
      ? error.message || error.info || error.status
      : '';
  return new Error(
    typeof message === 'string' && message.trim() ? message.trim() : fallback,
  );
}

function text(value) {
  if (Array.isArray(value)) return value[0] || '';
  return typeof value === 'string' ? value : '';
}
