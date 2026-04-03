import { Socket, _parseAddr } from 'net';
import { EventEmitter } from 'events';

function _notAvailable() {
    throw new Error('tls module requires async runtime (CLI)');
}

// --- TLSSocket ---

export class TLSSocket extends Socket {
    constructor(socket, options) {
        super(options);
        this.encrypted = true;
        this.authorized = true;
        this._tlsOptions = options || {};
    }

    getPeerCertificate() { return {}; }
    getProtocol() { return 'TLSv1.3'; }
    getCipher() { return { name: 'TLS_AES_256_GCM_SHA384', version: 'TLSv1.3' }; }
}

// --- tls.connect ---

export function connect(port, host, options, cb) {
    if (typeof __tls_connect === 'undefined') _notAvailable();

    // Normalize arguments
    if (typeof port === 'object' && port !== null) {
        // connect({port, host, ...}, cb)
        options = port;
        cb = host;
        host = options.host || 'localhost';
        port = options.port;
    } else {
        if (typeof host === 'function') { cb = host; host = 'localhost'; options = {}; }
        else if (typeof host === 'object' && host !== null) { options = host; cb = options; host = 'localhost'; }
        if (typeof options === 'function') { cb = options; options = {}; }
    }
    options = options || {};
    host = host || 'localhost';

    var socket = new TLSSocket(null, options);
    socket.connecting = true;
    socket.readyState = 'opening';

    var optsJson = JSON.stringify({
        rejectUnauthorized: options.rejectUnauthorized !== false,
        servername: options.servername || host,
        ca: options.ca || undefined,
    });

    if (cb) socket.once('secureConnect', cb);

    __tls_connect(host, port, optsJson).then(function(json) {
        var result = JSON.parse(json);
        socket._socketId = result.id;
        var remote = _parseAddr(result.remoteAddr);
        var local = _parseAddr(result.localAddr);
        socket.remoteAddress = remote.address;
        socket.remotePort = remote.port;
        socket.remoteFamily = remote.address.indexOf(':') >= 0 ? 'IPv6' : 'IPv4';
        socket.localAddress = local.address;
        socket.localPort = local.port;
        socket.connecting = false;
        socket.readyState = 'open';
        socket.emit('secureConnect');
        socket.emit('connect');
        socket._startReading();
    }).catch(function(e) {
        socket.connecting = false;
        socket.readyState = 'closed';
        socket.emit('error', e instanceof Error ? e : new Error(String(e)));
    });

    return socket;
}

// --- tls.createServer ---

export function createServer(options, connectionListener) {
    if (typeof __tls_create_server === 'undefined') _notAvailable();
    if (typeof options === 'function') {
        connectionListener = options;
        options = {};
    }
    options = options || {};

    var server = new EventEmitter();
    server._serverId = null;
    server.listening = false;
    server._address = null;
    if (connectionListener) server.on('secureConnection', connectionListener);

    server.listen = function(port, host, cb) {
        if (typeof host === 'function') { cb = host; host = '0.0.0.0'; }
        host = host || '0.0.0.0';

        var cert = options.cert || '';
        var key = options.key || '';

        __tls_create_server(cert, key, port, host).then(function(json) {
            var result = JSON.parse(json);
            server._serverId = result.id;
            server.listening = true;
            server._address = { port: result.port, family: 'IPv4', address: host };
            if (cb) cb();
            server.emit('listening');
            // Accept loop
            (async function() {
                while (server.listening && server._serverId !== null) {
                    var socketIdStr;
                    try { socketIdStr = await __net_accept(String(server._serverId)); }
                    catch (_) { break; }
                    if (!socketIdStr) break;

                    var socketId = parseInt(socketIdStr);
                    var socket = new TLSSocket();
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
                    server.emit('secureConnection', socket);
                }
            })();
        }).catch(function(e) {
            server.emit('error', e instanceof Error ? e : new Error(String(e)));
        });
        return server;
    };

    server.close = function(cb) {
        if (server._serverId !== null) {
            __net_server_close(String(server._serverId));
            server._serverId = null;
        }
        server.listening = false;
        if (cb) queueMicrotask(cb);
        queueMicrotask(function() { server.emit('close'); });
        return server;
    };

    server.address = function() { return server._address; };
    server.ref = function() { return server; };
    server.unref = function() { return server; };

    return server;
}

export default { TLSSocket, connect, createServer };
