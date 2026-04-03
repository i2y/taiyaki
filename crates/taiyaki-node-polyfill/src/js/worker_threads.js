import { EventEmitter } from 'events';

const _state = globalThis.__worker_threads_state || { isMainThread: true, threadId: 0, workerData: undefined };

export const isMainThread = _state.isMainThread;
export const threadId = _state.threadId;
export const workerData = _state.workerData;

class MessagePort extends EventEmitter {
    constructor() {
        super();
    }

    postMessage(data) {
        if (typeof __worker_parent_post !== 'undefined') {
            __worker_parent_post(JSON.stringify(data));
        }
    }

    _startListening() {
        const self = this;
        (async function pollLoop() {
            while (true) {
                let raw;
                try {
                    raw = await __worker_parent_poll();
                } catch (_) { break; }
                if (!raw) break;
                try {
                    self.emit('message', JSON.parse(raw));
                } catch (e) {
                    self.emit('message', raw);
                }
            }
            self.emit('close');
        })();
    }
}

export const parentPort = isMainThread ? null : (() => {
    const port = new MessagePort();
    port._startListening();
    return port;
})();

export class Worker extends EventEmitter {
    constructor(filename, options) {
        super();
        options = options || {};
        if (typeof __worker_spawn === 'undefined') {
            throw new Error('worker_threads is not available');
        }
        const result = JSON.parse(__worker_spawn(
            String(filename),
            JSON.stringify(options.workerData !== undefined ? options.workerData : null)
        ));
        this._id = result.id;
        this.threadId = result.threadId;
        this._exited = false;

        this._pollLoop();
    }

    async _pollLoop() {
        while (!this._exited) {
            let raw;
            try {
                raw = await __worker_poll_event(String(this._id));
            } catch (_) { break; }
            if (!raw) break;
            const ev = JSON.parse(raw);
            switch (ev.kind) {
                case 'message':
                    try {
                        this.emit('message', JSON.parse(ev.data));
                    } catch (e) {
                        this.emit('message', ev.data);
                    }
                    break;
                case 'error':
                    this.emit('error', new Error(ev.data));
                    break;
                case 'exit':
                    this._exited = true;
                    this.emit('exit', parseInt(ev.data) || 0);
                    break;
            }
        }
    }

    postMessage(data) {
        if (this._exited) throw new Error('Worker has been terminated');
        __worker_post_message(String(this._id), JSON.stringify(data));
    }

    terminate() {
        if (!this._exited) {
            this._exited = true;
            try { __worker_terminate(String(this._id)); } catch (_) {}
        }
        return Promise.resolve(0);
    }

    ref() { return this; }
    unref() { return this; }
}
