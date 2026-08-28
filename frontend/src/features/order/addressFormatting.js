/** 生成订单确认页中的完整收货信息，并避免直辖市名称重复。 */
export function formatDeliveryAddress(address) {
  const region = [
    address.province,
    address.city && address.city !== address.province ? address.city : '',
    address.district,
    address.detail_address,
  ]
    .filter(Boolean)
    .join('');

  return [address.receiver_name, address.receiver_phone, region]
    .filter(Boolean)
    .join(' · ');
}
