// CommonJS require() implementation
// Uses Rust host functions: __require_resolve, __require_read_file, __require_is_file
// Built-in modules (path, events, util, url, buffer) resolve by name.

(function() {
    const _cache = Object.create(null);

    function _require(specifier, fromDir) {
        // Normalize node: prefix for cache lookup
        const cacheKey = specifier.startsWith('node:') ? specifier.slice(5) : specifier;

        // Check cache
        if (_cache[cacheKey]) return _cache[cacheKey].exports;
        if (_cache[specifier]) return _cache[specifier].exports;

        // Resolve to absolute path (or builtin name for builtins)
        const resolved = __require_resolve(specifier, fromDir || _cwd());
        if (_cache[resolved]) return _cache[resolved].exports;

        // Read source: check built-in sources first (JSC CJS modules), then file system
        const source = (globalThis.__builtin_sources && globalThis.__builtin_sources[resolved])
            || __require_read_file(resolved);

        // JSON support
        if (resolved.endsWith('.json')) {
            const exports = JSON.parse(source);
            _cache[resolved] = { exports };
            return exports;
        }

        // Create module object
        const module = { exports: {}, id: resolved, filename: resolved, loaded: false };
        _cache[resolved] = module;

        // Determine dirname
        const lastSlash = resolved.lastIndexOf('/');
        const dirname = lastSlash > 0 ? resolved.slice(0, lastSlash) : '/';

        // Create child require bound to this module's directory
        function childRequire(spec) {
            return _require(spec, dirname);
        }
        childRequire.resolve = function(spec) {
            return __require_resolve(spec, dirname);
        };
        childRequire.cache = _cache;

        // Execute in CJS wrapper
        const wrapper = new Function('exports', 'require', 'module', '__filename', '__dirname',
            source + '\n//# sourceURL=' + resolved);
        wrapper(module.exports, childRequire, module, resolved, dirname);

        module.loaded = true;
        return module.exports;
    }

    function _cwd() {
        return typeof __path_cwd === 'function' ? __path_cwd() : '/';
    }

    // Set up global require
    const cwd = _cwd();
    function globalRequire(specifier) {
        return _require(specifier, cwd);
    }
    globalRequire.resolve = function(specifier) {
        return __require_resolve(specifier, cwd);
    };
    globalRequire.cache = _cache;

    globalThis.require = globalRequire;
    globalThis.module = { exports: {} };
    globalThis.exports = globalThis.module.exports;
})();
