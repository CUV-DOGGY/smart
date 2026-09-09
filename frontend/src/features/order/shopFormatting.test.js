import { describe, expect, it } from 'vitest';

import { formatBusinessHours } from './shopFormatting.js';

function period(day, openTime, closeTime) {
  return {
    day_of_week: day,
    open_time: openTime,
    close_time: closeTime,
  };
}

describe('formatBusinessHours', () => {
  it('groups consecutive days that use the same schedule', () => {
    const businessHours = Array.from({ length: 7 }, (_, day) =>
      period(day, '07:00:00', '22:00:00'),
    );

    expect(formatBusinessHours(businessHours)).toBe(
      '周一～周日 07:00—22:00',
    );
  });

  it('keeps different weekday and weekend schedules separate', () => {
    const businessHours = [
      ...Array.from({ length: 5 }, (_, day) =>
        period(day, '09:00:00', '21:00:00'),
      ),
      period(5, '10:00:00', '22:00:00'),
      period(6, '10:00:00', '22:00:00'),
    ];

    expect(formatBusinessHours(businessHours)).toBe(
      '周一～周五 09:00—21:00；周六～周日 10:00—22:00',
    );
  });

  it('compares the complete schedule for split business hours', () => {
    const businessHours = [
      period(0, '09:00:00', '12:00:00'),
      period(0, '13:00:00', '18:00:00'),
      period(1, '09:00:00', '12:00:00'),
      period(1, '13:00:00', '18:00:00'),
    ];

    expect(formatBusinessHours(businessHours)).toBe(
      '周一～周二 09:00—12:00、13:00—18:00',
    );
  });
});
