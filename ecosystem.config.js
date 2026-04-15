const fs = require('fs');
const path = require('path');

// Helper to parse .env file manually
function parseEnv(filePath) {
  const env = {};
  if (fs.existsSync(filePath)) {
    const content = fs.readFileSync(filePath, 'utf-8');
    content.split('\n').forEach((line) => {
      // Skip comments and empty lines
      if (line.trim().startsWith('#') || !line.trim()) return;
      const match = line.match(/^\s*([\w.-]+)\s*=\s*(.*)?$/);
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

// Deteksi path Python venv secara otomatis
function detectPythonPath() {
  const localVenv = path.resolve(__dirname, 'venv', 'bin', 'python');
  if (fs.existsSync(localVenv)) return localVenv;

  // Fallback ke path yang dikonfigurasi di env, atau default
  const envPython = envConfig.PYTHON_PATH;
  if (envPython && fs.existsSync(envPython)) return envPython;

  // Fallback absolut untuk server ramahai (production)
  const ramahai = '/home/ramahai/smartparking/smart-parking-engine/venv/bin/python';
  if (fs.existsSync(ramahai)) return ramahai;

  return 'python3'; // Fallback sistem
}

module.exports = {
  apps: [
    {
      name: 'smartparking-engine',
      script: './engine_parkir.py',
      interpreter: detectPythonPath(),
      cwd: __dirname,
      // Process management
      watch: false,
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 15,
      max_memory_restart: '1G',
      // Logging
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      error_file: './logs/engine-error.log',
      out_file: './logs/engine-out.log',
      merge_logs: true,
      // Environment variables
      env: {
        ...envConfig,
        PYTHONUNBUFFERED: '1',
        DEBUG_MODE: envConfig.DEBUG_MODE || 'False',
        // Pastikan API key konsisten dengan dashboard
        DASHBOARD_API_KEY: envConfig.DASHBOARD_API_KEY || 'mata-plat-secret-api-key-2026'
      },
      env_production: {
        ...envConfig,
        PYTHONUNBUFFERED: '1',
        DEBUG_MODE: 'False',
        DASHBOARD_API_KEY: envConfig.DASHBOARD_API_KEY || 'mata-plat-secret-api-key-2026'
      }
    }
  ]
};
