const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

function displayTime(value) {
  return typeof value === 'string' ? value.slice(0, 5) : '--:--';
}

export function formatBusinessHours(businessHours = []) {
  if (!businessHours.length) return '营业时间暂未提供';

  const schedulesByDay = Array.from({ length: 7 }, () => []);
  businessHours.forEach((period) => {
    if (
      !Number.isInteger(period.day_of_week) ||
      period.day_of_week < 0 ||
      period.day_of_week > 6
    ) {
      return;
    }
    schedulesByDay[period.day_of_week].push(
      `${displayTime(period.open_time)}—${displayTime(period.close_time)}`,
    );
  });

  const groupedSchedules = [];
  schedulesByDay.forEach((periods, day) => {
    if (!periods.length) return;
    const schedule = periods.sort().join('、');
    const previousGroup = groupedSchedules.at(-1);

    // 只有相邻日期的完整营业时段一致时才合并，避免误合并分段营业日。
    if (
      previousGroup &&
      previousGroup.endDay === day - 1 &&
      previousGroup.schedule === schedule
    ) {
      previousGroup.endDay = day;
      return;
    }
    groupedSchedules.push({ startDay: day, endDay: day, schedule });
  });

  return groupedSchedules
    .map(({ startDay, endDay, schedule }) => {
      const dayLabel =
        startDay === endDay
          ? WEEKDAY_LABELS[startDay]
          : `${WEEKDAY_LABELS[startDay]}～${WEEKDAY_LABELS[endDay]}`;
      return `${dayLabel} ${schedule}`;
    })
    .join('；');
}

export function formatShopAddress(shop) {
  if (shop.formatted_address) return shop.formatted_address;
  if (!shop.address) return '地址暂未提供';

  const { province, city, district, detail_address: detailAddress } = shop.address;
  return [province, city !== province ? city : '', district, detailAddress]
    .filter(Boolean)
    .join('');
}

export function formatMoney(value) {
  return `¥${Number(value || 0).toFixed(2)}`;
}
