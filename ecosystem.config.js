module.exports = {
  apps: [
    {
      name: 'mata-plat-engine',
      script: './engine_parkir.py',
      interpreter: './venv/bin/python',
      cwd: './',
      watch: false,
      autorestart: true,
      restart_delay: 5000,
      env: {
        PYTHONUNBUFFERED: '1',
        DEBUG_MODE: 'True'
      }
    }
  ]
};
