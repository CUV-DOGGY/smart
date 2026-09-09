import { createContext, useContext } from 'react';

export const OrderAttemptContext = createContext(null);

export function useOrderAttemptContext() {
  const context = useContext(OrderAttemptContext);
  if (!context) {
    throw new Error('useOrderAttemptContext must be used inside OrderCenterLayout');
  }
  return context;
}
