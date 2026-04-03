import { Duplex } from 'stream';
import { EventEmitter } from 'events';

function _notAvailable() {
    throw new Error('net module requires async runtime (CLI)');
}

export function _parseAddr(addrStr) {
    if (!addrStr) return { address: '', port: 0 };
    // Handle IPv6 "[::1]:port" and IPv4 "1.2.3.4:port"
    var lastColon = addrStr.lastIndexOf(':');
    if (lastColon < 0) return { address: addrStr, port: 0 };
    var addr = addrStr.substring(0, lastColon);
    var port = parseInt(addrStr.substring(lastColon + 1)) || 0;
    // Strip brackets from IPv6
    if (addr.startsWith('[') && addr.endsWith(']')) {
        addr = addr.substring(1, addr.length - 1);
    }
    return { address: addr, port: port };
}

// --- Socket (extends Duplex) ---

export class Socket extends Duplex {
    constructor(options) {
        super(options);
        this._socketId = null;
        this.remoteAddress = null;
        this.remotePort = null;
        this.remoteFamily = null;
        this.localAddress = null;
        this.localPort = null;
        this.connecting = false;
        this.destroyed = false;
        this.readyState = 'closed';
        this._reading = false;
    }

    connect(port, host, cb) {
        if (typeof __net_connect === 'undefined') _notAvailable();
        if (typeof port === 'object' && port !== null) {
            // connect({port, host}, cb)
            var opts = port;
            cb = host;
            host = opts.host || '127.0.0.1';
            port = opts.port;
        }
        if (typeof host === 'function') { cb = host; host = '127.0.0.1'; }
        host = host || '127.0.0.1';
        if (cb) this.once('connect', cb);
        this.connecting = true;
        this.readyState = 'opening';

        var self = this;
        __net_connect(host, port).then(function(json) {
            var result = JSON.parse(json);
            self._socketId = result.id;
            var remote = _parseAddr(result.remoteAddr);
            var local = _parseAddr(result.localAddr);
            self.remoteAddress = remote.address;
            self.remotePort = remote.port;
            self.remoteFamily = remote.address.indexOf(':') >= 0 ? 'IPv6' : 'IPv4';
            self.localAddress = local.address;
            self.localPort = local.port;
            self.connecting = false;
            self.readyState = 'open';
            self.emit('connect');
            self._startReading();
        }).catch(function(e) {
            self.connecting = false;
            self.readyState = 'closed';
            self.emit('error', e instanceof Error ? e : new Error(String(e)));
        });
        return this;
    }

    _startReading() {
        if (this._reading) return;
        this._reading = true;
        var self = this;
        (async function() {
            while (self._socketId !== null && !self.destroyed) {
                var evJSON;
                try { evJSON = await __net_read(String(self._socketId)); }
                catch (_) { break; }
                if (!evJSON) break;
                var ev = JSON.parse(evJSON);
                switch (ev.kind) {
                    case 'data': {
                        var bytes = new Uint8Array(__buffer_b64_to_bytes(ev.data));
                        self.push(bytes);
                        break;
                    }
                    case 'end':
                        self.push(null);
                        if (self.readyState === 'open') self.readyState = 'writeOnly';
                        self._reading = false;
                        return;
                    case 'error':
                        self.destroy(new Error(ev.data));
                        self._reading = false;
                        return;
                    case 'close':
                        self.destroy();
                        self._reading = false;
                        return;
                }
            }
            self._reading = false;
        })();
    }

    _read(_size) {
        // Data is pushed from _startReading; nothing needed here
    }

    _write(chunk, encoding, callback) {
        if (this._socketId === null) {
            callback(new Error('Socket is not connected'));
            return;
        }
        try {
            var b64 = _toB64(chunk);
            __net_write(String(this._socketId), b64);
            callback();
        } catch (e) {
            callback(e instanceof Error ? e : new Error(String(e)));
        }
    }

    _destroy(err, cb) {
        if (this._socketId !== null) {
            try { __net_close(String(this._socketId)); } catch (_) {}
            this._socketId = null;
        }
        this.readyState = 'closed';
        this.destroyed = true;
        if (cb) cb(err);
    }

    end(chunk, encoding, cb) {
        // Override to properly handle Duplex end
        if (typeof chunk === 'function') { cb = chunk; chunk = undefined; }
        if (typeof encoding === 'function') { cb = encoding; encoding = undefined; }
        if (chunk !== undefined && chunk !== null) {
            this.write(chunk, encoding);
        }
        // Half-close: send FIN but keep reading
        if (this._socketId !== null && typeof __net_shutdown !== 'undefined') {
            __net_shutdown(String(this._socketId));
        }
        if (this.readyState === 'open') this.readyState = 'readOnly';
        this.writable = false;
        this.writableEnded = true;
        if (cb) this.once('finish', cb);
        var self = this;
        queueMicrotask(function() {
            self.writableFinished = true;
            self.emit('finish');
        });
        return this;
    }

    setNoDelay(_noDelay) { return this; }
    setKeepAlive(_enable, _initialDelay) { return this; }
    setTimeout(timeout, cb) {
        if (cb) this.once('timeout', cb);
        return this;
    }
    ref() { return this; }
    unref() { return this; }
    address() {
        return {
            port: this.localPort,
            family: this.localAddress && this.localAddress.indexOf(':') >= 0 ? 'IPv6' : 'IPv4',
            address: this.localAddress,
        };
    }
}

// base64 helper
function _toB64(data) {
    if (typeof data === 'string') {
        var enc = new TextEncoder();
        var bytes = enc.encode(data);
        return __buffer_bytes_to_b64(JSON.stringify(Array.from(bytes)));
    }
    var bytes;
    if (data instanceof ArrayBuffer) bytes = new Uint8Array(data);
    else if (ArrayBuffer.isView(data)) bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    else if (data && data._data) bytes = new Uint8Array(data._data);
    else bytes = new Uint8Array(data);
    return __buffer_bytes_to_b64(JSON.stringify(Array.from(bytes)));
}

// --- Server ---

export class Server extends EventEmitter {
    constructor(options, connectionListener) {
        super();
        if (typeof options === 'function') {
            connectionListener = options;
            options = {};
        }
        this._options = options || {};
        this._serverId = null;
        this.listening = false;
        this._address = null;
        if (connectionListener) this.on('connection', connectionListener);
    }

    listen(port, host, backlog, cb) {
        if (typeof __net_listen === 'undefined') _notAvailable();
        // Normalize overloaded arguments
        if (typeof host === 'function') { cb = host; host = '0.0.0.0'; backlog = undefined; }
        if (typeof backlog === 'function') { cb = backlog; backlog = undefined; }
        host = host || '0.0.0.0';

        var self = this;
        __net_listen(port, host).then(function(json) {
            var result = JSON.parse(json);
            self._serverId = result.id;
            self.listening = true;
            self._address = { port: result.port, family: 'IPv4', address: result.address };
            if (cb) cb();
            self.emit('listening');
            self._acceptLoop();
        }).catch(function(e) {
            self.emit('error', e instanceof Error ? e : new Error(String(e)));
        });
        return this;
    }

    _acceptLoop() {
        var self = this;
        (async function() {
            while (self.listening && self._serverId !== null) {
                var socketIdStr;
                try { socketIdStr = await __net_accept(String(self._serverId)); }
                catch (_) { break; }
                if (!socketIdStr) break;

                var socketId = parseInt(socketIdStr);
                var socket = new Socket();
                socket._socketId = socketId;
                var localAddr = __net_local_addr(String(socketId));
                var remoteAddr = __net_remote_addr(String(socketId));
                var local = _parseAddr(localAddr);
                var remote = _parseAddr(remoteAddr);
                socket.localAddress = local.address;
                socket.localPort = local.port;
                socket.remoteAddress = remote.address;
                socket.remotePort = remote.port;
                socket.remoteFamily = remote.address.indexOf(':') >= 0 ? 'IPv6' : 'IPv4';
                socket.connecting = false;
                socket.readyState = 'open';
                socket._startReading();
                self.emit('connection', socket);
            }
        })();
    }

    close(cb) {
        if (this._serverId !== null) {
            __net_server_close(String(this._serverId));
            this._serverId = null;
        }
        this.listening = false;
        var self = this;
        if (cb) queueMicrotask(function() { cb(); });
        queueMicrotask(function() { self.emit('close'); });
        return this;
    }

    address() { return this._address; }
    ref() { return this; }
    unref() { return this; }
}

// --- Factory functions ---

export function createServer(options, connectionListener) {
    return new Server(options, connectionListener);
}

export function createConnection(port, host, cb) {
    var socket = new Socket();
    socket.connect(port, host, cb);
    return socket;
}

export var connect = createConnection;

// --- Utility functions ---

export function isIP(input) {
    if (isIPv4(input)) return 4;
    if (isIPv6(input)) return 6;
    return 0;
}

export function isIPv4(input) {
    if (typeof input !== 'string') return false;
    var parts = input.split('.');
    if (parts.length !== 4) return false;
    for (var i = 0; i < 4; i++) {
        var n = Number(parts[i]);
        if (!Number.isInteger(n) || n < 0 || n > 255) return false;
        if (parts[i] !== String(n)) return false; // no leading zeros
    }
    return true;
}

export function isIPv6(input) {
    if (typeof input !== 'string') return false;
    // Handle :: shorthand
    if (input === '::') return true;
    var doubleColonCount = (input.match(/::/g) || []).length;
    if (doubleColonCount > 1) return false;
    // Expand :: for validation
    var parts = input.split(':');
    if (parts.length < 2 || parts.length > 8) return false;
    var emptyCount = 0;
    for (var i = 0; i < parts.length; i++) {
        if (parts[i] === '') {
            emptyCount++;
            continue;
        }
        if (!/^[0-9a-fA-F]{1,4}$/.test(parts[i])) return false;
    }
    // With ::, we can have leading/trailing empties
    if (doubleColonCount === 1) return true;
    // Without ::, exactly 8 groups
    return parts.length === 8 && emptyCount === 0;
}

export default {
    Socket, Server, createServer, createConnection, connect,
    isIP, isIPv4, isIPv6,
};
