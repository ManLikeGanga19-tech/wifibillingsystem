import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import SuspendedNotice from './suspended';
import './index.css';

// Tiny path switch: /suspended is the PPPoE overdue page; everything else is the
// hotspot buy-access portal. (No router lib needed for two routes.)
const isSuspended = window.location.pathname.replace(/\/+$/, '').endsWith('/suspended');

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{isSuspended ? <SuspendedNotice /> : <App />}</React.StrictMode>
);
