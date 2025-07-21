const venom = require('venom-bot');
const path = require('path');

const number = process.argv[2];   // e.g. 923361915333
const message = process.argv[3];  // e.g. Hello from CLI

const tokenPath = path.resolve(__dirname, 'tokens');

venom.create({
  session: 'session-1',
  multidevice: true,
  headless: 'new',
  useChrome: true,
  refreshQR: 0,
  deleteSessionOnLogout: false,
  browserArgs: ['--no-sandbox'],
  sessionPath: tokenPath
}).then(client => {
  return client.sendText(`${number}@c.us`, message);
}).then(() => {
  console.log('✅ Message sent');
  setTimeout(() => process.exit(0), 10000);
}).catch(console.error);
