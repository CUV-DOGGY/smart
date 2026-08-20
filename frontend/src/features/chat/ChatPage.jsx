import { useCallback, useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { conversationApi, streamChat } from './api.js';
import {
  addUserMessage, appendDelta, cancelStream, failStream, finishStream,
  selectConversation, setConversationId, setConversations, setMessages,
  startNewConversation,
} from './chatSlice.js';
import { ChatComposer } from './ChatComposer.jsx';
import { ConversationPanel } from './ConversationPanel.jsx';
import { MessageList } from './MessageList.jsx';

export function ChatPage() {
  const dispatch = useDispatch();
  const chat = useSelector((state) => state.chat);
  const controllerRef = useRef(null);

  const loadConversations = useCallback(async () => {
    try {
      const response = await conversationApi.list();
      dispatch(setConversations(response.items));
    } catch (error) {
      dispatch(failStream(error.message));
    }
  }, [dispatch]);

  useEffect(() => {
    loadConversations();
    return () => controllerRef.current?.abort();
  }, [loadConversations]);

  const chooseConversation = async (id) => {
    controllerRef.current?.abort();
    dispatch(selectConversation(id));
    try {
      const response = await conversationApi.messages(id);
      dispatch(setMessages(response.items));
    } catch (error) {
      dispatch(failStream(error.message));
    }
  };

  const send = async (content) => {
    const controller = new AbortController();
    controllerRef.current = controller;
    dispatch(addUserMessage({
      message_id: crypto.randomUUID(),
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }));
    let completed = false;
    let streamError = null;
    try {
      await streamChat(
        { message: content, conversation_id: chat.currentId || undefined },
        {
          signal: controller.signal,
          onEvent(event) {
            if (event.type === 'meta') dispatch(setConversationId(event.conversation_id));
            if (event.type === 'token') dispatch(appendDelta(event.delta));
            if (event.type === 'done') {
              completed = true;
              dispatch(finishStream(event.message_id));
            }
            if (event.type === 'error') {
              streamError = event.message;
              dispatch(failStream(event.message));
            }
          },
        },
      );
      if (!completed && !streamError) dispatch(failStream('流式连接意外结束，请重试'));
      await loadConversations();
    } catch (error) {
      if (error.name === 'AbortError') dispatch(cancelStream());
      else dispatch(failStream(error.message || '消息发送失败'));
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  };

  const removeConversation = async (id) => {
    if (!window.confirm('确定删除这个会话吗？')) return;
    try {
      await conversationApi.remove(id);
      if (chat.currentId === id) dispatch(startNewConversation());
      await loadConversations();
    } catch (error) {
      dispatch(failStream(error.message));
    }
  };

  const cancel = () => controllerRef.current?.abort();
  return (
    <section className="chat-page">
      <ConversationPanel items={chat.conversations} currentId={chat.currentId} onSelect={chooseConversation} onNew={() => dispatch(startNewConversation())} onDelete={removeConversation} />
      <div className="chat-main">
        <header className="page-header compact"><div><p className="eyebrow">AI CUSTOMER SERVICE</p><h1>智能客服</h1></div><span className="status-dot">在线</span></header>
        <MessageList messages={chat.messages} streamingText={chat.streamingText} />
        {chat.error && <div className="alert error chat-error">{chat.error}{chat.lastMessage && <button className="ghost" onClick={() => send(chat.lastMessage)}>重试</button>}</div>}
        <ChatComposer disabled={chat.isStreaming} onSend={send} onCancel={cancel} />
      </div>
    </section>
  );
}
