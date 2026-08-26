import { useCallback, useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { conversationApi, resumeChat, streamChat } from './api.js';
import {
  addUserMessage,
  appendDelta,
  cancelStream,
  failStream,
  finishStream,
  selectConversation,
  setConversationId,
  setConversations,
  setMessages,
  setPendingConfirmation,
  setStatus,
  startNewConversation,
  startResume,
} from './chatSlice.js';
import { ConfirmationCard } from './ConfirmationCard.jsx';
import { ChatComposer } from './ChatComposer.jsx';
import { ConversationPanel } from './ConversationPanel.jsx';
import { MessageList } from './MessageList.jsx';

export function ChatPage() {
  const dispatch = useDispatch();
  const chat = useSelector((state) => state.chat);
  const controllerRef = useRef(null);
  const decisionKeysRef = useRef(new Map());

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
      dispatch(setPendingConfirmation(response.pending_confirmation));
    } catch (error) {
      dispatch(failStream(error.message));
    }
  };

  const send = async (content) => {
    const controller = new AbortController();
    controllerRef.current = controller;
    dispatch(
      addUserMessage({
        message_id: crypto.randomUUID(),
        role: 'user',
        content,
        created_at: new Date().toISOString(),
      }),
    );
    let completed = false;
    let streamError = null;
    try {
      await streamChat(
        { message: content, conversation_id: chat.currentId || undefined },
        {
          signal: controller.signal,
          onEvent(event) {
            if (event.type === 'meta')
              dispatch(setConversationId(event.conversation_id));
            if (event.type === 'token') dispatch(appendDelta(event.delta));
            if (event.type === 'status') dispatch(setStatus(event.label));
            if (event.type === 'confirmation_required')
              dispatch(setPendingConfirmation(event));
            if (event.type === 'done') {
              completed = true;
              dispatch(finishStream(event));
            }
            if (event.type === 'error') {
              streamError = event.message;
              dispatch(failStream(event.message));
            }
          },
        },
      );
      if (!completed && !streamError)
        dispatch(failStream('流式连接意外结束，请重试'));
      await loadConversations();
    } catch (error) {
      if (error.name === 'AbortError') dispatch(cancelStream());
      else dispatch(failStream(error.message || '消息发送失败'));
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  };

  const decide = async (decision) => {
    if (!chat.pendingConfirmation || !chat.currentId) return;
    const commandId =
      chat.pendingConfirmation.command_id ||
      chat.pendingConfirmation.interrupt_id;
    let idempotencyKey = decisionKeysRef.current.get(commandId);
    if (!idempotencyKey) {
      idempotencyKey = crypto.randomUUID();
      decisionKeysRef.current.set(commandId, idempotencyKey);
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    dispatch(startResume());
    let completed = false;
    try {
      await resumeChat(
        {
          conversation_id: chat.currentId,
          interrupt_id: chat.pendingConfirmation.interrupt_id,
          decision,
        },
        {
          signal: controller.signal,
          idempotencyKey,
          onEvent(event) {
            if (event.type === 'token') dispatch(appendDelta(event.delta));
            if (event.type === 'status') dispatch(setStatus(event.label));
            if (event.type === 'done') {
              completed = true;
              dispatch(finishStream(event));
            }
            if (event.type === 'error') dispatch(failStream(event.message));
          },
        },
      );
      if (completed) decisionKeysRef.current.delete(commandId);
      if (!completed) dispatch(failStream('确认连接意外结束，请重试'));
      await loadConversations();
    } catch (error) {
      if (error.name === 'AbortError') dispatch(cancelStream());
      else dispatch(failStream(error.message || '确认处理失败'));
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
      <ConversationPanel
        items={chat.conversations}
        currentId={chat.currentId}
        onSelect={chooseConversation}
        onNew={() => dispatch(startNewConversation())}
        onDelete={removeConversation}
      />
      <div className="chat-main">
        <header className="page-header compact">
          <div>
            <p className="eyebrow">AI CUSTOMER SERVICE</p>
            <h1>智能客服</h1>
          </div>
          <span className="status-dot">在线</span>
        </header>
        <MessageList
          messages={chat.messages}
          streamingText={chat.streamingText}
        />
        {chat.statusLabel && (
          <div className="agent-status">{chat.statusLabel}</div>
        )}
        <ConfirmationCard
          confirmation={chat.pendingConfirmation}
          disabled={chat.isStreaming}
          onDecision={decide}
        />
        {chat.error && (
          <div className="alert error chat-error">
            {chat.error}
            {chat.lastMessage && (
              <button className="ghost" onClick={() => send(chat.lastMessage)}>
                重试
              </button>
            )}
          </div>
        )}
        {!chat.pendingConfirmation && (
          <ChatComposer
            disabled={chat.isStreaming}
            onSend={send}
            onCancel={cancel}
          />
        )}
      </div>
    </section>
  );
}
