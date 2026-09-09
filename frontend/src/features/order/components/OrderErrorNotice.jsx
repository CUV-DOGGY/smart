import { useEffect, useState } from 'react';

const RECOVERY_SECONDS = 3;

export function OrderErrorNotice({ error }) {
  const [secondsRemaining, setSecondsRemaining] = useState(RECOVERY_SECONDS);

  useEffect(() => {
    const timer = globalThis.setInterval(() => {
      setSecondsRemaining((current) => Math.max(1, current - 1));
    }, 1000);
    return () => globalThis.clearInterval(timer);
  }, []);

  return (
    <div className="modal-backdrop notice-backdrop">
      <section className="modal result-notice error-notice" role="alertdialog">
        <div className="error-notice-content">
          <div className="error-notice-heading">
            <div className="result-notice-icon" aria-hidden="true">
              !
            </div>
            <div>
              <p className="eyebrow">ORDER NOT CREATED</p>
              <h2>订单创建失败</h2>
              <p className="error-notice-message">{error.message}</p>
            </div>
          </div>

          {error.fieldErrors?.length > 0 && (
            <ul className="error-field-list">
              {error.fieldErrors.map((item) => (
                <li key={`${item.field}-${item.message}`}>
                  {item.field ? `${item.field}：` : ''}
                  {item.message}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="error-notice-countdown" aria-live="polite">
          <span>{secondsRemaining}</span>
          <p>秒后自动返回订单详情</p>
          <div className="countdown-track" aria-hidden="true">
            <i />
          </div>
        </div>
      </section>
    </div>
  );
}
