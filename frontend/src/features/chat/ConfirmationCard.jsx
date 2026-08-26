import { OrderCancellationConfirmationCard } from './OrderCancellationConfirmationCard.jsx';
import { OrderConfirmationCard } from './OrderConfirmationCard.jsx';

const confirmationPresenters = {
  order: OrderConfirmationCard,
  order_cancellation: OrderCancellationConfirmationCard,
};

export function ConfirmationCard({ confirmation, disabled, onDecision }) {
  if (!confirmation) return null;
  const Presentation = confirmationPresenters[confirmation.presentation?.kind];
  if (Presentation) {
    return (
      <Presentation
        confirmation={confirmation}
        disabled={disabled}
        onDecision={onDecision}
      />
    );
  }
  return (
    <section className="confirmation-card" aria-label="待确认业务操作">
      <div>
        <p className="eyebrow">需要你的确认</p>
        <strong>{confirmation.summary}</strong>
        <p>只有点击“批准执行”后，系统才会调用真实业务服务。</p>
      </div>
      <div className="confirmation-actions">
        <button
          className="secondary"
          disabled={disabled}
          onClick={() => onDecision('reject')}
        >
          拒绝
        </button>
        <button
          className="primary"
          disabled={disabled}
          onClick={() => onDecision('approve')}
        >
          批准执行
        </button>
      </div>
    </section>
  );
}
