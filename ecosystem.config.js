const fs = require('fs');
const path = require('path');

// Helper to parse .env file manually
function parseEnv(filePath) {
  const env = {};
  if (fs.existsSync(filePath)) {
    const content = fs.readFileSync(filePath, 'utf-8');
    content.split('\n').forEach((line) => {
      const match = line.match(/^\s*([\w.-]+)\s*=\s*(.*)?\s*$/);
      if (match) {
        let value = match[2] || '';
        // Remove surrounding quotes
        if (value.startsWith('"') && value.endsWith('"')) value = value.slice(1, -1);
        else if (value.startsWith("'") && value.endsWith("'")) value = value.slice(1, -1);
        env[match[1]] = value.trim();
      }
    });
  }
  return env;
}

const envConfig = parseEnv(path.resolve(__dirname, '.env'));

module.exports = {
  apps: [
    {
      name: 'smartparking-engine',
      script: './engine_parkir.py',
      interpreter: '/home/ramahai/smartparking/smart-parking-engine/venv/bin/python',
      cwd: './',
      watch: false,
      autorestart: true,
      restart_delay: 5000,
      env: {
        ...envConfig,
        PYTHONUNBUFFERED: '1',
        DEBUG_MODE: envConfig.DEBUG_MODE || 'True'
      }
    }
  ]
};

