// vm module — sandboxed code execution

export function createContext(sandbox) {
    if (sandbox === undefined || sandbox === null) sandbox = {};
    Object.defineProperty(sandbox, '__isContext', { value: true, enumerable: false });
    return sandbox;
}

export function isContext(obj) {
    return obj !== null && typeof obj === 'object' && obj.__isContext === true;
}

export function runInNewContext(code, sandbox, options) {
    if (sandbox === undefined || sandbox === null) sandbox = {};
    if (typeof options === 'string') options = { filename: options };
    options = options || {};

    // Build a function that receives context keys as params and evals the code
    var keys = Object.keys(sandbox);
    var vals = keys.map(function(k) { return sandbox[k]; });

    var fn = new Function(...keys, '"use strict";\n return eval(' + JSON.stringify(code) + ');\n');
    return fn.apply(undefined, vals);
}

export function runInThisContext(code, options) {
    if (typeof options === 'string') options = { filename: options };
    return eval(code);
}

export class Script {
    constructor(code, options) {
        if (typeof options === 'string') options = { filename: options };
        this._code = code;
        this._options = options || {};
    }

    runInNewContext(sandbox, options) {
        return runInNewContext(this._code, sandbox, options);
    }

    runInThisContext(options) {
        return runInThisContext(this._code, options);
    }
}

export default { createContext, isContext, runInNewContext, runInThisContext, Script };
