import { useEffect } from 'react';
import { BrowserRouter, useLocation } from 'react-router-dom';

import { AppRoutes } from './app/routes.jsx';
import { AuthBootstrap } from './features/auth/AuthBootstrap.jsx';
import { traceRouteChange } from './shared/observability/index.js';

export default function App() {
  return (
    <BrowserRouter>
      <RouteTracing />
      <AuthBootstrap>
        <AppRoutes />
      </AuthBootstrap>
    </BrowserRouter>
  );
}

function RouteTracing() {
  const location = useLocation();
  useEffect(() => {
    traceRouteChange(location.pathname);
  }, [location.pathname]);
  return null;
}
