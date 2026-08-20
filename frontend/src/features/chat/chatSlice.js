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
  },
  reducers: {
    setConversations(state, action) { state.conversations = action.payload; },
    selectConversation(state, action) {
      state.currentId = action.payload;
      state.messages = [];
      state.error = null;
    },
    startNewConversation(state) {
      state.currentId = null;
      state.messages = [];
      state.streamingText = '';
      state.error = null;
    },
    setMessages(state, action) { state.messages = action.payload; },
    addUserMessage(state, action) {
      state.messages.push(action.payload);
      state.lastMessage = action.payload.content;
      state.streamingText = '';
      state.isStreaming = true;
      state.error = null;
    },
    setConversationId(state, action) { state.currentId = action.payload; },
    appendDelta(state, action) { state.streamingText += action.payload; },
    finishStream(state, action) {
      if (state.streamingText) {
        state.messages.push({
          message_id: action.payload,
          role: 'assistant',
          content: state.streamingText,
          created_at: new Date().toISOString(),
        });
      }
      state.streamingText = '';
      state.isStreaming = false;
    },
    failStream(state, action) {
      state.error = action.payload;
      state.streamingText = '';
      state.isStreaming = false;
    },
    cancelStream(state) {
      state.streamingText = '';
      state.isStreaming = false;
      state.error = null;
    },
  },
});

export const {
  setConversations, selectConversation, startNewConversation, setMessages,
  addUserMessage, setConversationId, appendDelta, finishStream, failStream,
  cancelStream,
} = chatSlice.actions;
export default chatSlice.reducer;
