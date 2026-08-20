import { BrowserRouter } from 'react-router-dom';

import { AppRoutes } from './app/routes.jsx';
import { AuthBootstrap } from './features/auth/AuthBootstrap.jsx';

export default function App() {
  return (
    <BrowserRouter>
      <AuthBootstrap><AppRoutes /></AuthBootstrap>
    </BrowserRouter>
  );
}
