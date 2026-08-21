import { describe, expect, it, vi } from 'vitest';

import { createSseParser } from './api.js';

describe('createSseParser', () => {
  it('parses events split across arbitrary chunks', () => {
    const onEvent = vi.fn();
    const parser = createSseParser(onEvent);
    parser.push('data: {"type":"meta","conversation');
    parser.push('_id":"c1"}\n\ndata: {"type":"token","delta":"你');
    parser.push('好"}\n\n');
    parser.finish();

    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onEvent).toHaveBeenNthCalledWith(1, {
      type: 'meta',
      conversation_id: 'c1',
    });
    expect(onEvent).toHaveBeenNthCalledWith(2, {
      type: 'token',
      delta: '你好',
    });
  });

  it('ignores malformed events without losing the next event', () => {
    const onEvent = vi.fn();
    const parser = createSseParser(onEvent);
    parser.push(
      'data: not-json\n\ndata: {"type":"done","message_id":"m1"}\n\n',
    );
    parser.finish();
    expect(onEvent).toHaveBeenCalledOnce();
    expect(onEvent).toHaveBeenCalledWith({ type: 'done', message_id: 'm1' });
  });
});
