import { createApp } from './app.js';
// Hostinger imports this entry file. listen() must run without a main-module guard.
const port = Number(process.env.PORT || 3000);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid PORT');
const server = createApp().listen(port, '0.0.0.0', () => console.log(`Farry listening on ${port}`));
for (const signal of ['SIGTERM', 'SIGINT']) process.once(signal, () => {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 10000).unref();
});
