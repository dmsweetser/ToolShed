const fs = require('fs');
const path = require('path');
const logDir = 'instance/logs';
if (!fs.existsSync(logDir)) {
    fs.mkdirSync(logDir, { recursive: true });
}
const logStream = fs.createWriteStream(path.join(logDir, 'app.log'), { flags: 'a' });

function log(level, message) {
    const timestamp = new Date().toISOString();
    const logMessage = `[${timestamp}] [${level}] ${message}\n`;
    logStream.write(logMessage);
    if (level === 'ERROR') console.error(logMessage);
    else if (level === 'WARN') console.warn(logMessage);
    else if (level === 'DEBUG') console.debug(logMessage);
    else console.log(message);
}

module.exports = {
    info: (msg) => log('INFO', msg),
    error: (msg) => log('ERROR', msg),
    warn: (msg) => log('WARN', msg),
    debug: (msg) => log('DEBUG', msg)
};