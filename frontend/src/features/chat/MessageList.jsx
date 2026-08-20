import { useEffect, useRef } from 'react';

export function MessageList({ messages, streamingText }) {
  const bottomRef = useRef(null);
  useEffect(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages, streamingText]);
  if (!messages.length && !streamingText) {
    return (
      <div className="chat-welcome">
        <div className="brand-mark">S</div>
        <h2>你好，我是 SmartServe</h2>
        <p>可以查询店铺、商品、地址和订单，也可以在明确确认后安全地下单或修改业务状态。</p>
      </div>
    );
  }
  return (
    <div className="message-list">
      {messages.map((message) => <Message key={message.message_id} role={message.role} content={message.content} />)}
      {streamingText && <Message role="assistant" content={streamingText} streaming />}
      <div ref={bottomRef} />
    </div>
  );
}

function Message({ role, content, streaming = false }) {
  return (
    <div className={`message-row ${role}`}>
      <span className="message-avatar">{role === 'assistant' ? 'S' : '你'}</span>
      <div className="message-bubble">{content}{streaming && <span className="cursor" />}</div>
    </div>
  );
}
