import { EventEmitter } from 'events';

export class Interface extends EventEmitter {
    constructor(options) {
        super();
        options = options || {};
        this._closed = false;
        this._prompt = options.prompt || '> ';
    }

    setPrompt(prompt) {
        this._prompt = prompt;
    }

    prompt(preserveCursor) {
        if (this._closed) return;
        if (typeof __process_stdout_write !== 'undefined') {
            __process_stdout_write(this._prompt);
        }
    }

    question(query, callback) {
        if (this._closed) return;
        if (typeof __readline_question === 'undefined') {
            throw new Error('readline is not available in this environment');
        }
        __readline_question(query).then(function(answer) {
            if (callback) callback(answer);
        });
    }

    close() {
        if (!this._closed) {
            this._closed = true;
            this.emit('close');
        }
    }

    write(data) {
        // no-op in non-TTY mode
    }

    // Start reading lines in a loop (for on('line') usage)
    _startReading() {
        if (typeof __readline_read_line === 'undefined') return;
        const self = this;
        (async function readLoop() {
            while (!self._closed) {
                let result;
                try {
                    result = JSON.parse(await __readline_read_line());
                } catch (_) { break; }
                if (result.closed) {
                    self.close();
                    break;
                }
                if (result.line !== undefined) {
                    self.emit('line', result.line);
                }
            }
        })();
    }
}

export function createInterface(options) {
    if (options && options.input && options.output) {
        // Node.js-style { input: process.stdin, output: process.stdout }
        // We ignore the actual streams and use our host functions
    }
    const rl = new Interface(options);
    let readingStarted = false;
    const origAddListener = EventEmitter.prototype.addListener;
    function patchedOn(event, listener) {
        origAddListener.call(rl, event, listener);
        if (event === 'line' && !readingStarted) {
            readingStarted = true;
            rl._startReading();
        }
        return rl;
    }
    rl.on = patchedOn;
    rl.addListener = patchedOn;
    return rl;
}

export default { createInterface, Interface };
