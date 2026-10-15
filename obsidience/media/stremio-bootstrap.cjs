// Load installation credentials inside the existing upstream server process.
// Values never appear in container arguments, OCI configuration or unit files.
const fs = require('node:fs');

try {
    const settings = JSON.parse(fs.readFileSync('/run/credentials/obsidience-media-stremio', 'utf8'));
    const prowlarr = fs.readFileSync('/run/credentials/obsidience-media-prowlarr', 'utf8').trim();
    if (!/^[a-f0-9]{64}$/.test(settings.secret_key)
            || !/^[a-f0-9]{64}$/.test(settings.owner_password)
            || !/^[A-Za-z0-9._~-]{16,4096}$/.test(prowlarr)) {
        throw new Error('invalid credential');
    }
    process.env.SECRET_KEY = settings.secret_key;
    process.env.AIOSTREAMS_AUTH = 'owner:' + settings.owner_password;
    process.env.BUILTIN_PROWLARR_API_KEY = prowlarr;
    import('/app/packages/server/dist/server.js').catch(() => {
        process.stderr.write('Media add-on startup failed; credential details withheld.\n');
        process.exit(1);
    });
} catch (_) {
    process.stderr.write('Media add-on credentials unavailable.\n');
    process.exit(1);
}
