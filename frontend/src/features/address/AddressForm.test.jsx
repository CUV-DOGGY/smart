import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AddressForm } from './AddressForm.jsx';

vi.mock('../map/MapPicker.jsx', () => ({
  MapPicker: () => null,
}));

afterEach(cleanup);

describe('AddressForm', () => {
  it('shows a clear message for an invalid phone number', () => {
    render(
      <AddressForm
        initialValue={null}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const phoneInput = screen.getByLabelText('手机号');

    fireEvent.change(phoneInput, { target: { value: '123456' } });
    fireEvent.invalid(phoneInput);

    expect(phoneInput.validationMessage).toBe('手机号码格式不正确');
    fireEvent.input(phoneInput, { target: { value: '13800138000' } });
    expect(phoneInput.validationMessage).toBe('');
  });
});
