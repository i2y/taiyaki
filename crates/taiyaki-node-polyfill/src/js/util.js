// Node.js util module polyfill

export function format(fmt, ...args) {
    if (typeof fmt !== 'string') {
        const parts = [];
        parts.push(inspect(fmt));
        for (let i = 0; i < args.length; i++) parts.push(inspect(args[i]));
        return parts.join(' ');
    }
    let i = 0;
    let str = fmt.replace(/%[sdifjoO%]/g, (match) => {
        if (match === '%%') return '%';
        if (i >= args.length) return match;
        const arg = args[i++];
        switch (match) {
            case '%s': return String(arg);
            case '%d': return Number(arg).toString();
            case '%i': return parseInt(arg, 10).toString();
            case '%f': return parseFloat(arg).toString();
            case '%j':
                try { return JSON.stringify(arg); }
                catch (_) { return '[Circular]'; }
            case '%o':
            case '%O':
                return inspect(arg);
            default: return match;
        }
    });
    for (; i < args.length; i++) {
        str += ' ' + inspect(args[i]);
    }
    return str;
}

export function inspect(obj, opts) {
    const depth = (opts && typeof opts.depth === 'number') ? opts.depth : 2;
    return _inspect(obj, depth, new Set());
}

function _inspect(value, depth, seen) {
    if (value === null) return 'null';
    if (value === undefined) return 'undefined';

    const type = typeof value;
    if (type === 'string') return "'" + value + "'";
    if (type === 'number' || type === 'boolean' || type === 'bigint') return String(value);
    if (type === 'symbol') return value.toString();
    if (type === 'function') return '[Function: ' + (value.name || '(anonymous)') + ']';

    if (seen.has(value)) return '[Circular]';
    seen.add(value);

    if (depth < 0) return Array.isArray(value) ? '[Array]' : '[Object]';

    if (value instanceof Error) return value.stack || value.toString();
    if (value instanceof Date) return value.toISOString();
    if (value instanceof RegExp) return value.toString();

    if (Array.isArray(value)) {
        if (value.length === 0) return '[]';
        const items = value.map(v => _inspect(v, depth - 1, seen));
        return '[ ' + items.join(', ') + ' ]';
    }

    const keys = Object.keys(value);
    if (keys.length === 0) return '{}';
    const pairs = keys.map(k => k + ': ' + _inspect(value[k], depth - 1, seen));
    return '{ ' + pairs.join(', ') + ' }';
}

export function promisify(original) {
    function fn(...args) {
        return new Promise((resolve, reject) => {
            args.push((err, ...values) => {
                if (err) reject(err);
                else if (values.length <= 1) resolve(values[0]);
                else resolve(values);
            });
            original.apply(this, args);
        });
    }
    return fn;
}

export function callbackify(original) {
    function fn(...args) {
        const callback = args.pop();
        original.apply(this, args).then(
            (ret) => callback(null, ret),
            (err) => callback(err)
        );
    }
    return fn;
}

export function inherits(ctor, superCtor) {
    ctor.super_ = superCtor;
    ctor.prototype = Object.create(superCtor.prototype, {
        constructor: { value: ctor, enumerable: false, writable: true, configurable: true },
    });
}

export function deprecate(fn, msg) {
    let warned = false;
    function deprecated(...args) {
        if (!warned) {
            console.warn('DeprecationWarning: ' + msg);
            warned = true;
        }
        return fn.apply(this, args);
    }
    return deprecated;
}

export const types = {
    isDate: (v) => v instanceof Date,
    isRegExp: (v) => v instanceof RegExp,
    isPromise: (v) => v instanceof Promise,
    isArray: (v) => Array.isArray(v),
    isBoolean: (v) => typeof v === 'boolean',
    isNull: (v) => v === null,
    isNullOrUndefined: (v) => v == null,
    isNumber: (v) => typeof v === 'number',
    isString: (v) => typeof v === 'string',
    isSymbol: (v) => typeof v === 'symbol',
    isUndefined: (v) => v === undefined,
    isFunction: (v) => typeof v === 'function',
    isObject: (v) => v !== null && typeof v === 'object',
};

// Re-export TextEncoder/TextDecoder if the engine provides them (not available in vanilla QuickJS)
export const TextEncoder = globalThis.TextEncoder || undefined;
export const TextDecoder = globalThis.TextDecoder || undefined;
