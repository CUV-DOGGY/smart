import { createSlice } from '@reduxjs/toolkit';

const chatSlice = createSlice({
  name: 'chat',
  initialState: {
    conversations: [],
    currentId: null,
    messages: [],
    streamingText: '',
    isStreaming: false,
    error: null,
    lastMessage: '',
    pendingConfirmation: null,
    statusLabel: null,
  },
  reducers: {
    setConversations(state, action) { state.conversations = action.payload; },
    selectConversation(state, action) {
      state.currentId = action.payload;
      state.messages = [];
      state.error = null;
      state.pendingConfirmation = null;
      state.statusLabel = null;
    },
    startNewConversation(state) {
      state.currentId = null;
      state.messages = [];
      state.streamingText = '';
      state.error = null;
      state.pendingConfirmation = null;
      state.statusLabel = null;
    },
    setMessages(state, action) { state.messages = action.payload; },
    addUserMessage(state, action) {
      state.messages.push(action.payload);
      state.lastMessage = action.payload.content;
      state.streamingText = '';
      state.isStreaming = true;
      state.error = null;
      state.statusLabel = '正在理解问题';
    },
    setConversationId(state, action) { state.currentId = action.payload; },
    appendDelta(state, action) {
      if (typeof action.payload === 'string') state.streamingText += action.payload;
    },
    setStatus(state, action) {
      state.statusLabel = typeof action.payload === 'string' ? action.payload : null;
    },
    setPendingConfirmation(state, action) { state.pendingConfirmation = action.payload; },
    startResume(state) {
      state.isStreaming = true;
      state.streamingText = '';
      state.error = null;
      state.statusLabel = '正在处理确认';
    },
    finishStream(state, action) {
      if (state.streamingText) {
        state.messages.push({
          message_id: action.payload.message_id,
          role: 'assistant',
          content: state.streamingText,
          created_at: new Date().toISOString(),
        });
      }
      state.streamingText = '';
      state.isStreaming = false;
      state.statusLabel = null;
      if (action.payload.outcome === 'completed') state.pendingConfirmation = null;
    },
    failStream(state, action) {
      state.error = action.payload;
      state.streamingText = '';
      state.isStreaming = false;
      state.statusLabel = null;
    },
    cancelStream(state) {
      state.streamingText = '';
      state.isStreaming = false;
      state.error = null;
      state.statusLabel = null;
    },
  },
});

export const {
  setConversations, selectConversation, startNewConversation, setMessages,
  addUserMessage, setConversationId, appendDelta, finishStream, failStream,
  cancelStream, setPendingConfirmation, setStatus, startResume,
} = chatSlice.actions;
export default chatSlice.reducer;
