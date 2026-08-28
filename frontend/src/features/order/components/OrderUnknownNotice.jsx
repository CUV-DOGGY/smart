export function OrderUnknownNotice({
  message,
  isSubmitting,
  onRetry,
  onExit,
}) {
  return (
    <div className="modal-backdrop notice-backdrop">
      <section
        className="modal result-notice unknown-notice"
        role="alertdialog"
        aria-modal="true"
      >
        <div className="result-notice-icon" aria-hidden="true">
          ?
        </div>
        <h2>订单结果尚未确认</h2>
        <p>{message}</p>
        <p className="muted">
          退出不会将订单标记为失败，待确认操作仍会安全保存在浏览器中。
        </p>
        <footer>
          <button
            type="button"
            className="secondary"
            disabled={isSubmitting}
            onClick={onExit}
          >
            退出并稍后确认
          </button>
          <button
            type="button"
            className="primary"
            disabled={isSubmitting}
            onClick={onRetry}
          >
            {isSubmitting ? '正在确认…' : '重试确认'}
          </button>
        </footer>
      </section>
    </div>
  );
}
