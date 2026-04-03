// Node.js child_process polyfill
import { EventEmitter } from 'events';
import { Readable, Writable } from 'stream';

// --- ChildProcess class ---

export class ChildProcess extends EventEmitter {
    constructor(pid) {
        super();
        this.pid = pid;
        this.exitCode = null;
        this.signalCode = null;
        this.killed = false;
        this.connected = false;
        this.stdin = null;
        this.stdout = null;
        this.stderr = null;
    }

    kill(signal) {
        if (this.killed || !this.pid) return false;
        signal = signal || 'SIGTERM';
        if (typeof __cp_kill !== 'undefined') {
            try {
                __cp_kill(String(this.pid), String(signal));
                this.killed = true;
                return true;
            } catch (_) { return false; }
        }
        return false;
    }

    ref() { return this; }
    unref() { return this; }
}


// --- Sync functions ---

function checkRunPermission(cmd) {
    if (typeof __check_run_permission !== 'undefined') {
        __check_run_permission(cmd);
    }
}

export function spawnSync(command, args, options) {
    if (typeof args === 'object' && !Array.isArray(args)) {
        options = args;
        args = [];
    }
    args = args || [];
    options = options || {};
    checkRunPermission(command);
    const resultJSON = __cp_spawn_sync(
        String(command),
        JSON.stringify(args),
        JSON.stringify(options)
    );
    const r = JSON.parse(resultJSON);
    return {
        pid: 0,
        output: [null, r.stdout, r.stderr],
        stdout: r.stdout,
        stderr: r.stderr,
        status: r.status,
        signal: r.signal || null,
        error: r.error ? new Error(r.error) : undefined,
    };
}

export function execSync(command, options) {
    options = options || {};
    checkRunPermission('sh');  // execSync always runs through shell
    return __cp_exec_sync(String(command), JSON.stringify(options));
}

export function execFileSync(file, args, options) {
    if (typeof args === 'object' && !Array.isArray(args)) {
        options = args;
        args = [];
    }
    args = args || [];
    options = options || {};
    checkRunPermission(file);
    return __cp_exec_file_sync(
        String(file),
        JSON.stringify(args),
        JSON.stringify(options)
    );
}


// --- Async functions (only available when CLI async host functions are registered) ---

let spawn, exec, execFile;

if (typeof __cp_spawn_async !== 'undefined') {
    spawn = function _spawn(command, args, options) {
        if (typeof args === 'object' && !Array.isArray(args)) {
            options = args;
            args = [];
        }
        args = args || [];
        options = options || {};

        const result = JSON.parse(__cp_spawn_async(
            String(command),
            JSON.stringify(args),
            JSON.stringify(options)
        ));
        const internalId = result.id;
        const cp = new ChildProcess(result.pid);

        const stdio = options.stdio || 'pipe';

        if (stdio === 'pipe' || (Array.isArray(stdio) && stdio[1] === 'pipe')) {
            cp.stdout = new Readable({ read() {} });
        }
        if (stdio === 'pipe' || (Array.isArray(stdio) && stdio[2] === 'pipe')) {
            cp.stderr = new Readable({ read() {} });
        }
        if (stdio === 'pipe' || (Array.isArray(stdio) && stdio[0] === 'pipe')) {
            cp.stdin = new Writable({
                write(chunk, _enc, cb) {
                    try {
                        __cp_stdin_write(String(internalId), typeof chunk === 'string' ? chunk : String(chunk));
                        cb();
                    } catch (e) { cb(e); }
                },
                final(cb) {
                    try {
                        if (typeof __cp_stdin_close !== 'undefined') __cp_stdin_close(String(internalId));
                    } catch (_) {}
                    cb();
                }
            });
        }

        (async function pollLoop() {
            while (true) {
                let evJSON;
                try {
                    evJSON = await __cp_poll_event(String(internalId));
                } catch (_) { break; }
                if (!evJSON) break;
                const ev = JSON.parse(evJSON);
                switch (ev.kind) {
                    case 'stdout':
                        if (cp.stdout) cp.stdout.push(ev.data);
                        break;
                    case 'stderr':
                        if (cp.stderr) cp.stderr.push(ev.data);
                        break;
                    case 'exit':
                        cp.exitCode = ev.code !== undefined ? ev.code : null;
                        cp.signalCode = ev.signal || null;
                        if (cp.stdout) cp.stdout.push(null);
                        if (cp.stderr) cp.stderr.push(null);
                        cp.emit('exit', cp.exitCode, cp.signalCode);
                        cp.emit('close', cp.exitCode, cp.signalCode);
                        // One more poll to trigger cleanup of the process entry
                        try { await __cp_poll_event(String(internalId)); } catch (_) {}
                        return;
                    case 'error':
                        cp.emit('error', new Error(ev.data));
                        return;
                }
            }
        })();

        return cp;
    };

    function _wrapExec(cp, label, callback) {
        let stdout = '';
        let stderr = '';
        if (cp.stdout) cp.stdout.on('data', (d) => { stdout += d; });
        if (cp.stderr) cp.stderr.on('data', (d) => { stderr += d; });
        cp._promise = new Promise((resolve, reject) => {
            cp.on('error', (err) => {
                if (callback) callback(err, stdout, stderr);
                else reject(err);
            });
            cp.on('close', (code, signal) => {
                if (code !== 0 && code !== null) {
                    const err = new Error(`Command failed: ${label}`);
                    err.code = code;
                    err.killed = cp.killed;
                    err.signal = signal;
                    err.stdout = stdout;
                    err.stderr = stderr;
                    if (callback) callback(err, stdout, stderr);
                    else reject(err);
                } else {
                    if (callback) callback(null, stdout, stderr);
                    else resolve({ stdout, stderr });
                }
            });
        });
        return cp;
    }

    exec = function _exec(command, options, callback) {
        if (typeof options === 'function') {
            callback = options;
            options = {};
        }
        return _wrapExec(spawn(command, [], { ...(options || {}), shell: true }), command, callback);
    };

    execFile = function _execFile(file, args, options, callback) {
        if (typeof args === 'function') {
            callback = args;
            args = [];
            options = {};
        } else if (typeof args === 'object' && !Array.isArray(args)) {
            callback = options;
            options = args;
            args = [];
        } else if (typeof options === 'function') {
            callback = options;
            options = {};
        }
        return _wrapExec(spawn(file, args || [], options || {}), file, callback);
    };
}

export { spawn, exec, execFile };

export default {
    ChildProcess,
    spawnSync, execSync, execFileSync,
    spawn, exec, execFile,
};
