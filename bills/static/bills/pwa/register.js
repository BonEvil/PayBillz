// Keep PWA support available through the browser and Omarchy, without in-app install UI.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js', {scope: '/', updateViaCache: 'none'}).catch(() => {
    // The normal web app still works if service workers are unavailable.
  });
}
