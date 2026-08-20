import { useEffect, useRef } from 'react';

export function MessageList({ messages, streamingText }) {
  const bottomRef = useRef(null);
  useEffect(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages, streamingText]);
  if (!messages.length && !streamingText) {
    return (
      <div className="chat-welcome">
        <div className="brand-mark">S</div>
        <h2>你好，我是 SmartServe</h2>
        <p>可以咨询商品、配送与售后问题。业务操作请前往地址或订单页面。</p>
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
