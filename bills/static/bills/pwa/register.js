(() => {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js', {scope: '/', updateViaCache: 'none'}).catch(() => {
      // The normal web app still works if service workers are unavailable.
    });
  }
  const button = document.getElementById('install-app');
  const status = document.getElementById('install-status');
  let prompt;
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    prompt = event;
    button.hidden = false;
  });
  button.addEventListener('click', async () => {
    if (!prompt) return;
    const installPrompt = prompt;
    prompt = null;
    button.hidden = true;
    await installPrompt.prompt();
    const result = await installPrompt.userChoice;
    status.textContent = result.outcome === 'accepted' ? 'PayBillz installation requested.' : '';
  });
  window.addEventListener('appinstalled', () => {
    prompt = null;
    button.hidden = true;
    status.textContent = 'PayBillz installed.';
  });
})();
