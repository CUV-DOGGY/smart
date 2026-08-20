import { createSlice } from '@reduxjs/toolkit';

const authSlice = createSlice({
  name: 'auth',
  initialState: { user: null, status: 'checking' },
  reducers: {
    authenticated(state, action) {
      state.user = action.payload;
      state.status = 'authenticated';
    },
    anonymous(state) {
      state.user = null;
      state.status = 'anonymous';
    },
  },
});

export const { authenticated, anonymous } = authSlice.actions;
export default authSlice.reducer;
