const __aInspect = typeof __inspect === 'function' ? __inspect : (v) => {
    if (v === null) return 'null';
    if (v === undefined) return 'undefined';
    if (typeof v === 'string') return JSON.stringify(v);
    try { return JSON.stringify(v); } catch { return String(v); }
};

class AssertionError extends Error {
    constructor(options) {
        const msg = options.message || `${options.operator}: ${__aInspect(options.actual)} ${options.operator} ${__aInspect(options.expected)}`;
        super(msg);
        this.name = 'AssertionError';
        this.actual = options.actual;
        this.expected = options.expected;
        this.operator = options.operator;
    }
}

function __deepEqual(a, b) {
    if (a === b) return true;
    if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return false;
    if (a instanceof Date && b instanceof Date) return a.getTime() === b.getTime();
    if (a instanceof RegExp && b instanceof RegExp) return a.source === b.source && a.flags === b.flags;
    if (Array.isArray(a) !== Array.isArray(b)) return false;
    const keysA = Object.keys(a);
    const keysB = Object.keys(b);
    if (keysA.length !== keysB.length) return false;
    for (const key of keysA) {
        if (!Object.prototype.hasOwnProperty.call(b, key)) return false;
        if (!__deepEqual(a[key], b[key])) return false;
    }
    return true;
}

function assert(value, message) {
    if (!value) {
        throw new AssertionError({
            message: message || 'The expression evaluated to a falsy value',
            actual: value,
            expected: true,
            operator: '==',
        });
    }
}

assert.ok = assert;

assert.strictEqual = function strictEqual(actual, expected, message) {
    if (actual !== expected) {
        throw new AssertionError({
            message: message,
            actual: actual,
            expected: expected,
            operator: '===',
        });
    }
};

assert.notStrictEqual = function notStrictEqual(actual, expected, message) {
    if (actual === expected) {
        throw new AssertionError({
            message: message,
            actual: actual,
            expected: expected,
            operator: '!==',
        });
    }
};

assert.deepStrictEqual = function deepStrictEqual(actual, expected, message) {
    if (!__deepEqual(actual, expected)) {
        throw new AssertionError({
            message: message,
            actual: actual,
            expected: expected,
            operator: 'deepStrictEqual',
        });
    }
};

assert.notDeepStrictEqual = function notDeepStrictEqual(actual, expected, message) {
    if (__deepEqual(actual, expected)) {
        throw new AssertionError({
            message: message,
            actual: actual,
            expected: expected,
            operator: 'notDeepStrictEqual',
        });
    }
};

assert.throws = function throws(fn, expected, message) {
    let threw = false;
    try { fn(); } catch (e) {
        threw = true;
        if (expected instanceof RegExp) {
            if (!expected.test(e.message)) {
                throw new AssertionError({
                    message: message || `Expected error matching ${expected}, got "${e.message}"`,
                    actual: e, expected: expected, operator: 'throws',
                });
            }
        } else if (typeof expected === 'function' && !(e instanceof expected)) {
            throw new AssertionError({
                message: message || `Expected error to be instance of ${expected.name}`,
                actual: e, expected: expected, operator: 'throws',
            });
        }
    }
    if (!threw) {
        throw new AssertionError({
            message: message || 'Missing expected exception',
            actual: undefined, expected: expected, operator: 'throws',
        });
    }
};

assert.doesNotThrow = function doesNotThrow(fn, message) {
    try { fn(); } catch (e) {
        throw new AssertionError({
            message: message || 'Got unwanted exception: ' + e.message,
            actual: e, expected: undefined, operator: 'doesNotThrow',
        });
    }
};

assert.fail = function fail(message) {
    throw new AssertionError({
        message: message || 'Failed',
        actual: undefined, expected: undefined, operator: 'fail',
    });
};

assert.ifError = function ifError(value) {
    if (value !== null && value !== undefined) {
        throw value instanceof Error ? value : new AssertionError({
            message: 'ifError got unwanted exception: ' + value,
            actual: value, expected: null, operator: 'ifError',
        });
    }
};

assert.AssertionError = AssertionError;

export default assert;
export { assert, AssertionError };
