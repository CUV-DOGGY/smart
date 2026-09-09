import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { setUnauthorizedHandler } from '../../shared/api/http.js';
import { tokenStorage } from '../../shared/storage/tokenStorage.js';
import { authApi } from './api.js';
import { anonymous, authenticated } from './authSlice.js';

export function AuthBootstrap({ children }) {
  const dispatch = useDispatch();
  const status = useSelector((state) => state.auth.status);

  useEffect(() => {
    const logout = () => {
      tokenStorage.clear();
      dispatch(anonymous());
    };
    const unregister = setUnauthorizedHandler(logout);
    if (!tokenStorage.get()) {
      dispatch(anonymous());
    } else {
      authApi.me().then((user) => dispatch(authenticated(user)), logout);
    }
    return unregister;
  }, [dispatch]);

  if (status === 'checking') {
    return (
      <div className="screen-center">
        <div className="spinner" />
        正在恢复登录状态…
      </div>
    );
  }
  return children;
}
