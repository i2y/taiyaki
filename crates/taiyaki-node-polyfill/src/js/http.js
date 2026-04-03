import { Readable, Writable } from 'stream';
import { EventEmitter } from 'events';

function _notAvailable(name) {
    throw new Error('http.' + name + ' requires async runtime (CLI)');
}

// --- base64 helpers ---

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

function _fromB64(b64) {
    return new Uint8Array(__buffer_b64_to_bytes(b64));
}

// --- IncomingMessage (extends Readable) ---

export class IncomingMessage extends Readable {
    constructor(data) {
        super();
        this.httpVersion = data.httpVersion || '1.1';
        this.method = data.method || undefined;
        this.url = data.url || undefined;
        this.headers = data.headers || {};
        this.statusCode = data.statusCode || undefined;
        this.statusMessage = data.statusMessage || '';
        this.complete = false;
        this.socket = null;
        if (data.body) {
            this.push(data.body);
        }
        this.push(null);
        this.complete = true;
    }
    _read() {}
}

// --- ServerResponse (extends Writable) ---

export class ServerResponse extends Writable {
    constructor(serverId, reqId) {
        super();
        this._serverId = serverId;
        this._reqId = reqId;
        this.statusCode = 200;
        this.statusMessage = 'OK';
        this._headers = {};
        this._headersSent = false;
        this._body = [];
        this.finished = false;
    }

    setHeader(name, value) { this._headers[name.toLowerCase()] = String(value); return this; }
    getHeader(name) { return this._headers[name.toLowerCase()]; }
    removeHeader(name) { delete this._headers[name.toLowerCase()]; }
    hasHeader(name) { return name.toLowerCase() in this._headers; }
    getHeaders() { return Object.assign({}, this._headers); }
    get headersSent() { return this._headersSent; }

    writeHead(statusCode, statusMessage, headers) {
        if (typeof statusMessage === 'object') { headers = statusMessage; statusMessage = undefined; }
        this.statusCode = statusCode;
        if (statusMessage) this.statusMessage = statusMessage;
        if (headers) {
            for (var k in headers) {
                if (headers.hasOwnProperty(k)) {
                    this._headers[k.toLowerCase()] = String(headers[k]);
                }
            }
        }
        this._headersSent = true;
        return this;
    }

    _write(chunk, encoding, callback) {
        if (typeof chunk === 'string') {
            this._body.push(chunk);
        } else if (chunk instanceof Uint8Array || ArrayBuffer.isView(chunk)) {
            this._body.push(new TextDecoder().decode(chunk));
        } else {
            this._body.push(String(chunk));
        }
        callback();
    }

    _final(cb) {
        var bodyStr = this._body.join('');
        var b64 = _toB64(bodyStr);
        __http_server_respond(
            String(this._serverId),
            String(this._reqId),
            this.statusCode,
            JSON.stringify(this._headers),
            b64
        );
        this.finished = true;
        this._headersSent = true;
        cb();
    }
}

// --- Server ---

export class Server extends EventEmitter {
    constructor(options, requestListener) {
        super();
        if (typeof options === 'function') {
            requestListener = options;
            options = {};
        }
        this._options = options || {};
        this._serverId = null;
        this.listening = false;
        this._address = null;
        if (requestListener) this.on('request', requestListener);
    }

    listen(port, host, cb) {
        if (typeof __http_create_server === 'undefined') _notAvailable('createServer');
        if (typeof host === 'function') { cb = host; host = '0.0.0.0'; }
        host = host || '0.0.0.0';

        var self = this;
        this._serverId = __http_create_server();

        __http_server_listen(this._serverId, port, host).then(function(json) {
            var result = JSON.parse(json);
            self.listening = true;
            self._address = { port: result.port, family: 'IPv4', address: host };
            if (cb) cb();
            self.emit('listening');
            self._requestLoop();
        }).catch(function(e) {
            self.emit('error', e instanceof Error ? e : new Error(String(e)));
        });
        return this;
    }

    _requestLoop() {
        var self = this;
        (async function() {
            while (self.listening && self._serverId !== null) {
                var reqJSON;
                try { reqJSON = await __http_server_next_request(self._serverId); }
                catch (_) { break; }
                if (!reqJSON) break;

                var raw = JSON.parse(reqJSON);
                // Decode base64 body
                var bodyStr = '';
                if (raw.body) {
                    try {
                        var bodyBytes = _fromB64(raw.body);
                        bodyStr = new TextDecoder().decode(bodyBytes);
                    } catch (_) {
                        bodyStr = raw.body;
                    }
                }
                var req = new IncomingMessage({
                    method: raw.method,
                    url: raw.url,
                    headers: raw.headers,
                    httpVersion: raw.httpVersion,
                    body: bodyStr || undefined,
                });
                var res = new ServerResponse(self._serverId, raw.id);
                self.emit('request', req, res);
            }
        })();
    }

    close(cb) {
        if (this._serverId !== null) {
            __http_server_close(this._serverId);
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

// --- ClientRequest (extends Writable) ---

export class ClientRequest extends Writable {
    constructor(options, cb) {
        super();
        this._options = typeof options === 'string' ? _parseUrl(options) : options;
        this._body = [];
        this._response = null;
        this._ended = false;
        if (cb) this.once('response', cb);
    }

    _write(chunk, encoding, callback) {
        if (typeof chunk === 'string') {
            this._body.push(chunk);
        } else if (chunk instanceof Uint8Array || ArrayBuffer.isView(chunk)) {
            this._body.push(new TextDecoder().decode(chunk));
        } else {
            this._body.push(String(chunk));
        }
        callback();
    }

    _final(cb) {
        if (typeof __http_request === 'undefined') {
            cb(new Error('http.request requires async runtime (CLI)'));
            return;
        }
        var self = this;
        var opts = this._options;
        var body = this._body.join('');

        __http_request(JSON.stringify({
            hostname: opts.hostname || opts.host || 'localhost',
            port: opts.port || (opts.protocol === 'https:' ? 443 : 80),
            path: opts.path || '/',
            method: opts.method || 'GET',
            headers: opts.headers || {},
            body: body,
            protocol: opts.protocol || 'http:',
        })).then(function(json) {
            var raw = JSON.parse(json);
            var res = new IncomingMessage({
                statusCode: raw.status,
                statusMessage: raw.statusText || '',
                headers: raw.headers || {},
                body: raw.body || undefined,
                httpVersion: '1.1',
            });
            self._response = res;
            self.emit('response', res);
            cb();
        }).catch(function(e) {
            self.emit('error', e instanceof Error ? e : new Error(String(e)));
            cb();
        });
    }
}

function _parseUrl(urlStr) {
    var u = new URL(urlStr);
    return {
        protocol: u.protocol,
        hostname: u.hostname,
        port: u.port || (u.protocol === 'https:' ? 443 : 80),
        path: u.pathname + u.search,
        method: 'GET',
    };
}

// --- Factory functions ---

export function createServer(options, requestListener) {
    return new Server(options, requestListener);
}

export function request(options, cb) {
    var opts = typeof options === 'string' ? _parseUrl(options) : options;
    var req = new ClientRequest(opts, cb);
    return req;
}

export function get(options, cb) {
    var opts = typeof options === 'string' ? _parseUrl(options) : options;
    opts.method = 'GET';
    var req = request(opts, cb);
    req.end();
    return req;
}

// --- STATUS_CODES ---
export var STATUS_CODES = {
    100: 'Continue', 101: 'Switching Protocols', 200: 'OK', 201: 'Created',
    204: 'No Content', 301: 'Moved Permanently', 302: 'Found',
    304: 'Not Modified', 400: 'Bad Request', 401: 'Unauthorized',
    403: 'Forbidden', 404: 'Not Found', 405: 'Method Not Allowed',
    500: 'Internal Server Error', 502: 'Bad Gateway', 503: 'Service Unavailable',
    504: 'Gateway Timeout',
};

export var METHODS = [
    'GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'CONNECT', 'OPTIONS', 'TRACE', 'PATCH'
];

export default {
    createServer, request, get, Server, IncomingMessage, ServerResponse,
    ClientRequest, STATUS_CODES, METHODS,
};
