// Node.js url module polyfill
// Provides both WHATWG URL (if available) and legacy Node.js url API.

// Use globalThis.URL if available, otherwise provide a minimal implementation
const _URL = typeof globalThis.URL === 'function' ? globalThis.URL : null;
const _URLSearchParams = typeof globalThis.URLSearchParams === 'function' ? globalThis.URLSearchParams : null;

// Simple URL parser for environments without WHATWG URL
function _parseURL(urlString) {
    const result = {
        protocol: null, slashes: null, auth: null, host: null,
        port: null, hostname: null, hash: null, search: null,
        query: null, pathname: null, path: null, href: urlString,
    };

    let rest = urlString;

    // Protocol
    const protoMatch = rest.match(/^([a-zA-Z][a-zA-Z0-9+\-.]*:)/);
    if (protoMatch) {
        result.protocol = protoMatch[1];
        rest = rest.slice(protoMatch[1].length);
    }

    // Slashes
    if (rest.startsWith('//')) {
        result.slashes = true;
        rest = rest.slice(2);

        // Auth
        const atIdx = rest.indexOf('@');
        const slashIdx = rest.indexOf('/');
        if (atIdx !== -1 && (slashIdx === -1 || atIdx < slashIdx)) {
            result.auth = rest.slice(0, atIdx);
            rest = rest.slice(atIdx + 1);
        }

        // Host (hostname:port)
        const hostEnd = rest.indexOf('/');
        const hostStr = hostEnd === -1 ? rest : rest.slice(0, hostEnd);
        rest = hostEnd === -1 ? '' : rest.slice(hostEnd);

        const bracketIdx = hostStr.indexOf(']');
        let colonIdx;
        if (bracketIdx !== -1) {
            colonIdx = hostStr.indexOf(':', bracketIdx);
        } else {
            colonIdx = hostStr.indexOf(':');
        }

        if (colonIdx !== -1) {
            result.hostname = hostStr.slice(0, colonIdx);
            result.port = hostStr.slice(colonIdx + 1);
            result.host = hostStr;
        } else {
            result.hostname = hostStr;
            result.host = hostStr;
        }
    }

    // Hash
    const hashIdx = rest.indexOf('#');
    if (hashIdx !== -1) {
        result.hash = rest.slice(hashIdx);
        rest = rest.slice(0, hashIdx);
    }

    // Search
    const searchIdx = rest.indexOf('?');
    if (searchIdx !== -1) {
        result.search = rest.slice(searchIdx);
        result.query = result.search.slice(1);
        rest = rest.slice(0, searchIdx);
    }

    result.pathname = rest || (result.slashes ? '/' : null);
    result.path = (result.pathname || '') + (result.search || '');
    result.href = urlString;

    return result;
}

// Legacy url.parse()
export function parse(urlString, parseQueryString, slashesDenoteHost) {
    if (_URL) {
        try {
            const u = new _URL(urlString);
            const result = {
                protocol: u.protocol,
                slashes: true,
                auth: u.username ? (u.password ? u.username + ':' + u.password : u.username) : null,
                host: u.host,
                port: u.port || null,
                hostname: u.hostname,
                hash: u.hash || null,
                search: u.search || null,
                query: parseQueryString ? _searchParamsToObj(u.searchParams) : (u.search ? u.search.slice(1) : null),
                pathname: u.pathname,
                path: u.pathname + (u.search || ''),
                href: u.href,
            };
            return result;
        } catch (_) {
            // Fall through to manual parser
        }
    }

    const result = _parseURL(urlString);
    if (parseQueryString && result.query) {
        result.query = _parseQS(result.query);
    }
    return result;
}

function _searchParamsToObj(params) {
    const obj = {};
    params.forEach((v, k) => { obj[k] = v; });
    return obj;
}

function _parseQS(qs) {
    const obj = {};
    if (!qs) return obj;
    const pairs = qs.split('&');
    for (const pair of pairs) {
        const eqIdx = pair.indexOf('=');
        if (eqIdx === -1) {
            obj[decodeURIComponent(pair)] = '';
        } else {
            obj[decodeURIComponent(pair.slice(0, eqIdx))] = decodeURIComponent(pair.slice(eqIdx + 1));
        }
    }
    return obj;
}

// Legacy url.format()
export function format(urlObj) {
    if (typeof urlObj === 'string') return urlObj;
    if (_URL && urlObj instanceof _URL) return urlObj.href;

    let result = '';
    if (urlObj.protocol) result += urlObj.protocol;
    if (urlObj.slashes || (urlObj.protocol && urlObj.protocol.endsWith(':'))) result += '//';
    if (urlObj.auth) result += urlObj.auth + '@';
    if (urlObj.hostname) {
        result += urlObj.hostname;
        if (urlObj.port) result += ':' + urlObj.port;
    } else if (urlObj.host) {
        result += urlObj.host;
    }
    if (urlObj.pathname) result += urlObj.pathname;
    if (urlObj.search) {
        result += urlObj.search.startsWith('?') ? urlObj.search : '?' + urlObj.search;
    }
    if (urlObj.hash) {
        result += urlObj.hash.startsWith('#') ? urlObj.hash : '#' + urlObj.hash;
    }
    return result;
}

// Legacy url.resolve()
export function resolve(from, to) {
    if (_URL) {
        try { return new _URL(to, from).href; } catch (_) {}
    }
    // Basic fallback
    if (to.match(/^[a-zA-Z][a-zA-Z0-9+\-.]*:/)) return to; // absolute
    const parsed = _parseURL(from);
    if (to.startsWith('/')) {
        return (parsed.protocol || '') + (parsed.slashes ? '//' : '') +
               (parsed.auth ? parsed.auth + '@' : '') +
               (parsed.host || '') + to;
    }
    const base = parsed.pathname ? parsed.pathname.replace(/\/[^/]*$/, '/') : '/';
    return (parsed.protocol || '') + (parsed.slashes ? '//' : '') +
           (parsed.auth ? parsed.auth + '@' : '') +
           (parsed.host || '') + base + to;
}

export function fileURLToPath(url) {
    let pathname;
    if (typeof url === 'string') {
        if (!url.startsWith('file:')) throw new TypeError('The URL must be of scheme file');
        // Extract pathname from file:// URL
        pathname = url.slice(7); // remove 'file://'
        // Handle file:///path (3 slashes)
        if (pathname.startsWith('/')) {
            // Already has leading slash, pathname is correct
        }
    } else if (_URL && url instanceof _URL) {
        if (url.protocol !== 'file:') throw new TypeError('The URL must be of scheme file');
        pathname = url.pathname;
    } else {
        throw new TypeError('The URL must be a string or URL object');
    }
    return decodeURIComponent(pathname);
}

export function pathToFileURL(path) {
    let resolved = path;
    if (!path.startsWith('/')) resolved = '/' + path;
    const encoded = encodeURI(resolved).replace(/#/g, '%23').replace(/\?/g, '%3F');
    if (_URL) return new _URL('file://' + encoded);
    return { href: 'file://' + encoded, pathname: resolved, protocol: 'file:' };
}

// Re-export URL/URLSearchParams if available
export const URL = _URL;
export const URLSearchParams = _URLSearchParams;
