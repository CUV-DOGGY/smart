import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MessageList } from './MessageList.jsx';

describe('MessageList', () => {
  it('keeps automatic scrolling inside the message list', () => {
    const { container, rerender } = render(
      <MessageList
        messages={[{ message_id: 'u1', role: 'user', content: '你好' }]}
        streamingText=""
      />,
    );
    const list = container.querySelector('.message-list');
    Object.defineProperty(list, 'scrollHeight', { configurable: true, value: 420 });

    rerender(
      <MessageList
        messages={[{ message_id: 'u1', role: 'user', content: '你好' }]}
        streamingText="你"
      />,
    );

    expect(list.scrollTop).toBe(420);
  });

  it('renders a safe fallback for invalid persisted content', () => {
    render(
      <MessageList
        messages={[{ message_id: 'a1', role: 'assistant', content: { text: 'bad' } }]}
        streamingText=""
      />,
    );

    expect(screen.getByText('消息内容格式异常，请刷新会话后重试。')).toBeInTheDocument();
  });
});
