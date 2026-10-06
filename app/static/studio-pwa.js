if ('serviceWorker' in navigator && window.isSecureContext && location.pathname.startsWith('/admin/')) {
  navigator.serviceWorker.register('/admin/studio-sw.js', {scope: '/admin/'}).catch(() => {});
}
