// Node.js EventEmitter polyfill

let _defaultMaxListeners = 10;

export class EventEmitter {
    constructor() {
        this._events = Object.create(null);
        this._maxListeners = undefined;
    }

    static get defaultMaxListeners() {
        return _defaultMaxListeners;
    }

    static set defaultMaxListeners(n) {
        _defaultMaxListeners = n;
    }

    getMaxListeners() {
        return this._maxListeners === undefined
            ? EventEmitter.defaultMaxListeners
            : this._maxListeners;
    }

    setMaxListeners(n) {
        this._maxListeners = n;
        return this;
    }

    emit(type, ...args) {
        const listeners = this._events[type];
        if (!listeners || listeners.length === 0) {
            if (type === 'error') {
                const err = args[0];
                throw err instanceof Error ? err : new Error('Unhandled error: ' + err);
            }
            return false;
        }
        // Copy to avoid mutation during iteration
        const handlers = listeners.slice();
        for (let i = 0; i < handlers.length; i++) {
            const entry = handlers[i];
            if (entry.once) {
                this.removeListener(type, entry.listener);
            }
            entry.listener.apply(this, args);
        }
        return true;
    }

    on(type, listener) {
        return this.addListener(type, listener);
    }

    addListener(type, listener) {
        if (!this._events[type]) this._events[type] = [];
        this._events[type].push({ listener, once: false });
        return this;
    }

    prependListener(type, listener) {
        if (!this._events[type]) this._events[type] = [];
        this._events[type].unshift({ listener, once: false });
        return this;
    }

    once(type, listener) {
        if (!this._events[type]) this._events[type] = [];
        this._events[type].push({ listener, once: true });
        return this;
    }

    prependOnceListener(type, listener) {
        if (!this._events[type]) this._events[type] = [];
        this._events[type].unshift({ listener, once: true });
        return this;
    }

    removeListener(type, listener) {
        return this.off(type, listener);
    }

    off(type, listener) {
        const listeners = this._events[type];
        if (!listeners) return this;
        for (let i = listeners.length - 1; i >= 0; i--) {
            if (listeners[i].listener === listener) {
                listeners.splice(i, 1);
                break;
            }
        }
        if (listeners.length === 0) delete this._events[type];
        return this;
    }

    removeAllListeners(type) {
        if (type === undefined) {
            this._events = Object.create(null);
        } else {
            delete this._events[type];
        }
        return this;
    }

    listeners(type) {
        const listeners = this._events[type];
        if (!listeners) return [];
        return listeners.map(e => e.listener);
    }

    rawListeners(type) {
        const listeners = this._events[type];
        if (!listeners) return [];
        return listeners.slice();
    }

    listenerCount(type) {
        const listeners = this._events[type];
        return listeners ? listeners.length : 0;
    }

    eventNames() {
        return Object.keys(this._events);
    }
}

export default EventEmitter;
