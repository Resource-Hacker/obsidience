import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'node:crypto';
import { closeSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { MemoryStorageDriver, StorageService, fromJson, toJson } from '@matter/main';

// The encryption key comes only from systemd's private credential filesystem. Native Matter
// keys and counters remain in memory; every write is encrypted and fsynced before returning.
export function installEncryptedStorage(environment, directory, credentialPath) {
    const keyStat = lstatSync(credentialPath);
    if (!keyStat.isFile() || keyStat.uid !== process.getuid() || (keyStat.mode & 0o077)) throw new Error('credential_permissions');
    const key = readFileSync(credentialPath);
    if (key.length !== 32) throw new Error('credential_format');
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    const dirStat = lstatSync(directory);
    if (!dirStat.isDirectory() || dirStat.uid !== process.getuid() || (dirStat.mode & 0o077)) throw new Error('storage_permissions');
    let failed = false;
    class EncryptedStorage extends MemoryStorageDriver {
        static id = 'obsidience-encrypted';
        static create(namespace) { const driver = new this(namespace.namespace); driver.initialize(); return driver; }
        constructor(namespace) {
            super();
            this.namespace = namespace;
            this.path = join(directory, createHash('sha256').update(namespace).digest('hex') + '.enc');
        }
        initialize() {
            this.assertHealthy();
            try {
                const stat = lstatSync(this.path);
                if (!stat.isFile() || stat.uid !== process.getuid() || (stat.mode & 0o077) || stat.size > 16 * 1024 * 1024) throw new Error('storage_permissions');
                const envelope = readFileSync(this.path);
                if (envelope.length < 32 || envelope.subarray(0, 4).toString() !== 'OML1') throw new Error('storage_format');
                const decipher = createDecipheriv('aes-256-gcm', key, envelope.subarray(4, 16));
                decipher.setAAD(Buffer.from(this.namespace));
                decipher.setAuthTag(envelope.subarray(16, 32));
                const plain = Buffer.concat([decipher.update(envelope.subarray(32)), decipher.final()]);
                try { this.store = fromJson(plain.toString()); } finally { plain.fill(0); }
            } catch (error) {
                if (error.code !== 'ENOENT') { failed = true; throw new Error('storage_unavailable'); }
            }
            super.initialize();
        }
        assertHealthy() { if (failed) throw new Error('storage_unavailable'); }
        persist() {
            this.assertHealthy();
            const temporary = this.path + '.' + randomBytes(8).toString('hex') + '.new';
            let fd;
            try {
                const nonce = randomBytes(12);
                const cipher = createCipheriv('aes-256-gcm', key, nonce);
                cipher.setAAD(Buffer.from(this.namespace));
                const plain = Buffer.from(toJson(this.data));
                let encrypted;
                try { encrypted = Buffer.concat([cipher.update(plain), cipher.final()]); } finally { plain.fill(0); }
                fd = openSync(temporary, 'wx', 0o600);
                writeFileSync(fd, Buffer.concat([Buffer.from('OML1'), nonce, cipher.getAuthTag(), encrypted]));
                fsyncSync(fd); closeSync(fd); fd = undefined;
                renameSync(temporary, this.path);
                const directoryFd = openSync(directory, 'r');
                try { fsyncSync(directoryFd); } finally { closeSync(directoryFd); }
            } catch {
                failed = true;
                throw new Error('storage_unavailable');
            } finally {
                if (fd !== undefined) closeSync(fd);
                try { unlinkSync(temporary); } catch {}
            }
        }
        set(...args) { this.assertHealthy(); super.set(...args); this.persist(); }
        delete(...args) { this.assertHealthy(); super.delete(...args); this.persist(); }
        clearAll(...args) { this.assertHealthy(); super.clearAll(...args); this.persist(); }
    }
    const storage = environment.get(StorageService);
    storage.registerDriver(EncryptedStorage);
    storage.configuredDriver = EncryptedStorage.id;
    return { assertHealthy() { if (failed) throw new Error('storage_unavailable'); } };
}
