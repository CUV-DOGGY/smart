import { useLayoutEffect, useRef } from 'react';

export function MessageList({ messages, streamingText }) {
  const listRef = useRef(null);

  useLayoutEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages, streamingText]);

  if (!messages.length && !streamingText) {
    return (
      <div className="chat-welcome">
        <div className="brand-mark">S</div>
        <h2>你好，我是 SmartServe</h2>
        <p>
          可以查询店铺、商品、地址和订单，也可以在明确确认后安全地下单或修改业务状态。
        </p>
      </div>
    );
  }
  return (
    <div className="message-list" ref={listRef}>
      {messages.map((message, index) => (
        <Message
          key={message.message_id || `${message.role || 'unknown'}-${index}`}
          role={message.role}
          content={safeMessageText(message.content)}
        />
      ))}
      {streamingText && (
        <Message role="assistant" content={streamingText} streaming />
      )}
    </div>
  );
}

function Message({ role, content, streaming = false }) {
  return (
    <div className={`message-row ${role}`}>
      <span className="message-avatar">
        {role === 'assistant' ? 'S' : '你'}
      </span>
      <div className="message-bubble">
        {content}
        {streaming && <span className="cursor" />}
      </div>
    </div>
  );
}

function safeMessageText(content) {
  if (typeof content === 'string') return content;
  if (content == null) return '';
  return '消息内容格式异常，请刷新会话后重试。';
}
