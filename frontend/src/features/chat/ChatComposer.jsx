import { useState } from 'react';

export function ChatComposer({ disabled, onSend, onCancel }) {
  const [text, setText] = useState('');
  const submit = (event) => {
    event.preventDefault();
    const value = text.trim();
    if (!value || disabled) return;
    setText('');
    onSend(value);
  };
  return (
    <form className="chat-composer" onSubmit={submit}>
      <textarea value={text} maxLength="1000" rows="2" placeholder="输入你的问题…" onChange={(event) => setText(event.target.value)} onKeyDown={(event) => {
        if (event.key === 'Enter' && !event.shiftKey) submit(event);
      }} />
      {disabled ? <button type="button" className="secondary" onClick={onCancel}>停止</button> : <button className="primary">发送</button>}
    </form>
  );
}
