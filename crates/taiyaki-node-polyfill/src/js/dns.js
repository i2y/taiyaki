// dns module — async DNS resolution via Rust host functions

function _notAvailable() {
    throw new Error('dns module requires async runtime (CLI)');
}

function _normalizeArgs(args) {
    var hostname = args[0];
    var options = {};
    var callback;
    if (typeof args[1] === 'function') {
        callback = args[1];
    } else if (typeof args[1] === 'object' && args[1] !== null) {
        options = args[1];
        callback = args[2];
    } else if (typeof args[1] === 'number') {
        options = { family: args[1] };
        callback = args[2];
    }
    return { hostname: hostname, options: options, callback: callback };
}

// --- dns.lookup(hostname, [options], callback) ---

export function lookup(hostname, options, callback) {
    if (typeof __dns_lookup === 'undefined') _notAvailable();
    var args = _normalizeArgs([hostname, options, callback]);
    var cb = args.callback;
    var opts = args.options;

    if (cb) {
        __dns_lookup(args.hostname).then(function(json) {
            var result = JSON.parse(json);
            if (opts.family && opts.family !== result.family) {
                cb(new Error('getaddrinfo ENOTFOUND ' + args.hostname));
            } else {
                cb(null, result.address, result.family);
            }
        }).catch(function(e) {
            cb(e instanceof Error ? e : new Error(String(e)));
        });
    } else {
        return __dns_lookup(args.hostname).then(function(json) {
            var result = JSON.parse(json);
            if (opts.family && opts.family !== result.family) {
                throw new Error('getaddrinfo ENOTFOUND ' + args.hostname);
            }
            return result;
        });
    }
}

// --- dns.resolve(hostname, [rrtype], callback) ---

export function resolve(hostname, rrtype, callback) {
    if (typeof __dns_resolve === 'undefined') _notAvailable();
    if (typeof rrtype === 'function') { callback = rrtype; rrtype = 'A'; }
    rrtype = rrtype || 'A';

    if (callback) {
        __dns_resolve(hostname, rrtype).then(function(json) {
            callback(null, JSON.parse(json));
        }).catch(function(e) {
            callback(e instanceof Error ? e : new Error(String(e)));
        });
    } else {
        return __dns_resolve(hostname, rrtype).then(function(json) {
            return JSON.parse(json);
        });
    }
}

export function resolve4(hostname, callback) {
    return resolve(hostname, 'A', callback);
}

export function resolve6(hostname, callback) {
    return resolve(hostname, 'AAAA', callback);
}

// --- dns.promises ---

export var promises = {
    lookup: function(hostname, options) {
        return lookup(hostname, options || {});
    },
    resolve: function(hostname, rrtype) {
        return resolve(hostname, rrtype);
    },
    resolve4: function(hostname) {
        return resolve(hostname, 'A');
    },
    resolve6: function(hostname) {
        return resolve(hostname, 'AAAA');
    },
};

export default { lookup, resolve, resolve4, resolve6, promises };
