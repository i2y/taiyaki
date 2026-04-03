// Node.js stream module polyfill (event-based, NOT Web Streams)
import { EventEmitter } from 'events';

// --- Readable ---

export class Readable extends EventEmitter {
    constructor(opts) {
        super();
        opts = opts || {};
        this.highWaterMark = opts.highWaterMark !== undefined ? opts.highWaterMark : 16384;
        this.objectMode = !!opts.objectMode;
        if (typeof opts.read === 'function') this._read = opts.read;
        if (typeof opts.destroy === 'function') this._destroy = opts.destroy;

        this._buffer = [];
        this._bufferSize = 0;
        this._flowing = null;       // null = paused-initial, true = flowing, false = paused
        this._ended = false;        // push(null) received
        this._endEmitted = false;
        this._destroyed = false;
        this._reading = false;
        this.readable = true;
        this.readableEnded = false;
        this.errored = null;
    }

    // Override point — subclasses implement this
    _read(_size) {}

    _destroy(err, cb) { cb(err); }

    push(chunk) {
        if (this._ended) return false;
        if (chunk === null) {
            this._ended = true;
            if (this._buffer.length === 0) this._emitEnd();
            return false;
        }
        const size = this.objectMode ? 1 : (typeof chunk === 'string' ? chunk.length : (chunk && chunk.byteLength || 0));
        this._buffer.push(chunk);
        this._bufferSize += size;

        if (this._flowing === true) {
            this._drainBuffer();
        }

        return this._bufferSize < this.highWaterMark;
    }

    read(n) {
        if (this._destroyed) return null;
        if (n === 0) return null;

        if (this._buffer.length === 0) {
            if (this._ended) {
                if (!this._endEmitted) this._emitEnd();
                return null;
            }
            return null;
        }

        if (n === undefined || n >= this._bufferSize || this.objectMode) {
            // Return all buffered data
            let result;
            if (this.objectMode) {
                result = this._buffer.shift();
                this._bufferSize = this._buffer.length;
            } else if (this._buffer.length === 1) {
                result = this._buffer.shift();
                this._bufferSize = 0;
            } else {
                result = this._concatBuffer();
                this._buffer.length = 0;
                this._bufferSize = 0;
            }

            if (this._ended && this._buffer.length === 0) {
                queueMicrotask(() => this._emitEnd());
            }
            return result;
        }

        // Partial read
        const chunk = this._buffer[0];
        if (typeof chunk === 'string') {
            const result = chunk.slice(0, n);
            if (n >= chunk.length) {
                this._buffer.shift();
            } else {
                this._buffer[0] = chunk.slice(n);
            }
            this._bufferSize -= result.length;
            return result;
        }
        return this._buffer.shift();
    }

    _concatBuffer() {
        if (this._buffer.length === 0) return '';
        if (typeof this._buffer[0] === 'string') {
            return this._buffer.join('');
        }
        // ArrayBuffer/Uint8Array concat
        const total = new Uint8Array(this._bufferSize);
        let offset = 0;
        for (const buf of this._buffer) {
            const arr = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
            total.set(arr, offset);
            offset += arr.byteLength;
        }
        return total;
    }

    _emitEnd() {
        if (this._endEmitted || this._destroyed) return;
        this._endEmitted = true;
        this.readable = false;
        this.readableEnded = true;
        this.emit('end');
        queueMicrotask(() => this.emit('close'));
    }

    _drainBuffer() {
        while (this._buffer.length > 0 && this._flowing === true) {
            const chunk = this._buffer.shift();
            const size = this.objectMode ? 1 : (typeof chunk === 'string' ? chunk.length : (chunk && chunk.byteLength || 0));
            this._bufferSize -= size;
            this.emit('data', chunk);
        }
        if (this._ended && this._buffer.length === 0) {
            this._emitEnd();
        }
    }

    resume() {
        if (this._destroyed) return this;
        this._flowing = true;
        this._drainBuffer();
        if (!this._ended && !this._reading && this._buffer.length < this.highWaterMark) {
            this._reading = true;
            this._read(this.highWaterMark);
            this._reading = false;
        }
        return this;
    }

    pause() {
        this._flowing = false;
        return this;
    }

    pipe(dest, opts) {
        const onData = (chunk) => {
            const canWrite = dest.write(chunk);
            if (!canWrite) {
                this.pause();
            }
        };
        const onDrain = () => { this.resume(); };
        const onEnd = () => { if (!opts || opts.end !== false) dest.end(); };
        const onError = (err) => { dest.destroy(err); };

        this.on('data', onData);
        dest.on('drain', onDrain);
        this.on('end', onEnd);
        this.on('error', onError);

        dest.emit('pipe', this);

        // Store cleanup info for unpipe
        if (!this._pipes) this._pipes = [];
        this._pipes.push({ dest, onData, onDrain, onEnd, onError });

        this.resume();
        return dest;
    }

    unpipe(dest) {
        if (!this._pipes) return this;
        if (!dest) {
            for (const p of this._pipes) {
                this.off('data', p.onData);
                p.dest.off('drain', p.onDrain);
                this.off('end', p.onEnd);
                this.off('error', p.onError);
                p.dest.emit('unpipe', this);
            }
            this._pipes.length = 0;
        } else {
            const idx = this._pipes.findIndex(p => p.dest === dest);
            if (idx !== -1) {
                const p = this._pipes[idx];
                this.off('data', p.onData);
                dest.off('drain', p.onDrain);
                this.off('end', p.onEnd);
                this.off('error', p.onError);
                this._pipes.splice(idx, 1);
                dest.emit('unpipe', this);
            }
        }
        return this;
    }

    setEncoding(_enc) {
        // Simplified: we always deal with strings for now
        return this;
    }

    destroy(err) {
        if (this._destroyed) return this;
        this._destroyed = true;
        this.readable = false;
        this._buffer.length = 0;
        this._bufferSize = 0;
        this._destroy(err || null, (e) => {
            if (e) this.emit('error', e);
            this.emit('close');
        });
        return this;
    }

    // Auto-flow when 'data' listener is attached
    on(type, listener) {
        super.on(type, listener);
        if (type === 'data' && this._flowing !== false) {
            this._flowing = true;
            queueMicrotask(() => {
                this._drainBuffer();
                // Trigger _read if buffer is empty and not ended
                if (!this._ended && this._buffer.length === 0) {
                    this._read(this.highWaterMark);
                }
            });
        }
        if (type === 'readable') {
            if (this._buffer.length > 0) {
                queueMicrotask(() => this.emit('readable'));
            }
        }
        return this;
    }

    [Symbol.asyncIterator]() {
        const stream = this;
        return {
            _ended: false,
            next() {
                if (this._ended) return Promise.resolve({ done: true, value: undefined });
                return new Promise((resolve, reject) => {
                    const chunk = stream.read();
                    if (chunk !== null) {
                        return resolve({ done: false, value: chunk });
                    }
                    if (stream._endEmitted || stream.readableEnded) {
                        this._ended = true;
                        return resolve({ done: true, value: undefined });
                    }
                    const onData = (data) => {
                        cleanup();
                        resolve({ done: false, value: data });
                    };
                    const onEnd = () => {
                        cleanup();
                        this._ended = true;
                        resolve({ done: true, value: undefined });
                    };
                    const onError = (err) => {
                        cleanup();
                        reject(err);
                    };
                    const cleanup = () => {
                        stream.off('data', onData);
                        stream.off('end', onEnd);
                        stream.off('error', onError);
                    };
                    stream.once('data', onData);
                    stream.once('end', onEnd);
                    stream.once('error', onError);
                    stream.resume();
                });
            },
            return() {
                stream.destroy();
                return Promise.resolve({ done: true, value: undefined });
            },
        };
    }
}

Readable.from = function(iterable, opts) {
    const stream = new Readable(opts);
    if (iterable[Symbol.asyncIterator]) {
        const iterator = iterable[Symbol.asyncIterator]();
        let pushing = false;
        stream._read = function() {
            if (pushing) return;
            pushing = true;
            iterator.next().then(({ done, value }) => {
                pushing = false;
                if (done) { stream.push(null); }
                else {
                    stream.push(value);
                    // Continue reading if still flowing
                    if (stream._flowing) stream._read();
                }
            }).catch(err => stream.destroy(err));
        };
    } else if (iterable[Symbol.iterator]) {
        const iterator = iterable[Symbol.iterator]();
        stream._read = function() {
            let result;
            while (!(result = iterator.next()).done) {
                if (!stream.push(result.value)) return; // backpressure
            }
            stream.push(null);
        };
    } else {
        throw new TypeError('argument must be an iterable');
    }
    return stream;
};


// --- Writable ---

export class Writable extends EventEmitter {
    constructor(opts) {
        super();
        opts = opts || {};
        this.highWaterMark = opts.highWaterMark !== undefined ? opts.highWaterMark : 16384;
        this.objectMode = !!opts.objectMode;
        if (typeof opts.write === 'function') this._write = opts.write;
        if (typeof opts.writev === 'function') this._writev = opts.writev;
        if (typeof opts.destroy === 'function') this._destroy = opts.destroy;
        if (typeof opts.final === 'function') this._final = opts.final;

        this._buffer = [];
        this._bufferSize = 0;
        this._writing = false;
        this._ending = false;
        this._finished = false;
        this._destroyed = false;
        this._corked = 0;
        this.writable = true;
        this.writableEnded = false;
        this.writableFinished = false;
        this.errored = null;
    }

    // Override point
    _write(chunk, encoding, callback) { callback(); }

    _writev(chunks, callback) {
        // Default: write one at a time
        let i = 0;
        const next = (err) => {
            if (err) return callback(err);
            if (i >= chunks.length) return callback();
            this._write(chunks[i].chunk, chunks[i].encoding, next);
            i++;
        };
        next();
    }

    _destroy(err, cb) { cb(err); }

    _final(cb) { cb(); }

    write(chunk, encoding, callback) {
        if (typeof encoding === 'function') { callback = encoding; encoding = undefined; }
        if (this._destroyed || this._ending) {
            const err = new Error('write after end');
            if (callback) queueMicrotask(() => callback(err));
            this.emit('error', err);
            return false;
        }

        const size = this.objectMode ? 1 : (typeof chunk === 'string' ? chunk.length : (chunk && chunk.byteLength || 0));

        if (this._corked > 0 || this._writing) {
            this._buffer.push({ chunk, encoding, callback });
            this._bufferSize += size;
            return this._bufferSize < this.highWaterMark;
        }

        this._writing = true;
        this._doWrite(chunk, encoding, (err) => {
            this._writing = false;
            if (err) {
                this.errored = err;
                if (callback) callback(err);
                this.emit('error', err);
                return;
            }
            if (callback) callback();
            this._clearBuffer();
        });

        this._bufferSize += size;
        const ret = this._bufferSize < this.highWaterMark;
        this._bufferSize -= size;
        return ret;
    }

    _doWrite(chunk, encoding, cb) {
        this._write(chunk, encoding, cb);
    }

    _clearBuffer() {
        if (this._corked > 0 || this._buffer.length === 0) {
            if (this._ending && this._buffer.length === 0 && !this._writing) {
                this._finish();
            }
            if (this._buffer.length === 0 && this._bufferSize > 0) {
                this._bufferSize = 0;
            }
            if (this._buffer.length === 0) {
                this.emit('drain');
            }
            return;
        }

        const entry = this._buffer.shift();
        const size = this.objectMode ? 1 : (typeof entry.chunk === 'string' ? entry.chunk.length : (entry.chunk && entry.chunk.byteLength || 0));
        this._bufferSize -= size;
        this._writing = true;
        this._doWrite(entry.chunk, entry.encoding, (err) => {
            this._writing = false;
            if (err) {
                this.errored = err;
                if (entry.callback) entry.callback(err);
                this.emit('error', err);
                return;
            }
            if (entry.callback) entry.callback();
            this._clearBuffer();
        });
    }

    end(chunk, encoding, callback) {
        if (typeof chunk === 'function') { callback = chunk; chunk = undefined; encoding = undefined; }
        if (typeof encoding === 'function') { callback = encoding; encoding = undefined; }
        if (this._ending) return this;
        if (chunk !== undefined && chunk !== null) {
            this.write(chunk, encoding);
        }
        this._ending = true;
        this.writableEnded = true;
        if (callback) this.once('finish', callback);
        if (!this._writing && this._buffer.length === 0) {
            this._finish();
        }
        return this;
    }

    _finish() {
        if (this._finished) return;
        this._final((err) => {
            if (err) {
                this.errored = err;
                this.emit('error', err);
                return;
            }
            this._finished = true;
            this.writable = false;
            this.writableFinished = true;
            this.emit('finish');
            queueMicrotask(() => this.emit('close'));
        });
    }

    cork() { this._corked++; }

    uncork() {
        if (this._corked > 0) this._corked--;
        if (this._corked === 0 && !this._writing) {
            this._clearBuffer();
        }
    }

    destroy(err) {
        if (this._destroyed) return this;
        this._destroyed = true;
        this.writable = false;
        this._buffer.length = 0;
        this._bufferSize = 0;
        this._destroy(err || null, (e) => {
            if (e) this.emit('error', e);
            this.emit('close');
        });
        return this;
    }
}


// --- Duplex ---
// JS single-inheritance: extend Readable, mixin Writable methods

export class Duplex extends Readable {
    constructor(opts) {
        super(opts);
        opts = opts || {};
        // Initialize Writable state
        this.highWaterMark = opts.highWaterMark !== undefined ? opts.highWaterMark : 16384;
        if (typeof opts.write === 'function') this._write = opts.write;
        if (typeof opts.writev === 'function') this._writev = opts.writev;
        if (typeof opts.final === 'function') this._final = opts.final;

        this._wBuffer = [];
        this._wBufferSize = 0;
        this._writing = false;
        this._ending = false;
        this._finished = false;
        this._wDestroyed = false;
        this._corked = 0;
        this.writable = true;
        this.writableEnded = false;
        this.writableFinished = false;
    }

    _write(chunk, encoding, callback) { callback(); }
    _writev(chunks, callback) { Writable.prototype._writev.call(this, chunks, callback); }
    _final(cb) { cb(); }

    write(chunk, encoding, callback) {
        if (typeof encoding === 'function') { callback = encoding; encoding = undefined; }
        if (this._wDestroyed || this._ending) {
            const err = new Error('write after end');
            if (callback) queueMicrotask(() => callback(err));
            this.emit('error', err);
            return false;
        }
        const size = this.objectMode ? 1 : (typeof chunk === 'string' ? chunk.length : (chunk && chunk.byteLength || 0));

        if (this._corked > 0 || this._writing) {
            this._wBuffer.push({ chunk, encoding, callback });
            this._wBufferSize += size;
            return this._wBufferSize < this.highWaterMark;
        }

        this._writing = true;
        this._doWrite(chunk, encoding, (err) => {
            this._writing = false;
            if (err) {
                if (callback) callback(err);
                this.emit('error', err);
                return;
            }
            if (callback) callback();
            this._clearWBuffer();
        });

        return (this._wBufferSize + size) < this.highWaterMark;
    }

    _doWrite(chunk, encoding, cb) { this._write(chunk, encoding, cb); }

    _clearWBuffer() {
        if (this._corked > 0 || this._wBuffer.length === 0) {
            if (this._ending && this._wBuffer.length === 0 && !this._writing) {
                this._finishWrite();
            }
            if (this._wBuffer.length === 0 && this._wBufferSize > 0) {
                this._wBufferSize = 0;
            }
            if (this._wBuffer.length === 0) {
                this.emit('drain');
            }
            return;
        }

        const entry = this._wBuffer.shift();
        const size = this.objectMode ? 1 : (typeof entry.chunk === 'string' ? entry.chunk.length : (entry.chunk && entry.chunk.byteLength || 0));
        this._wBufferSize -= size;
        this._writing = true;
        this._doWrite(entry.chunk, entry.encoding, (err) => {
            this._writing = false;
            if (err) {
                if (entry.callback) entry.callback(err);
                this.emit('error', err);
                return;
            }
            if (entry.callback) entry.callback();
            this._clearWBuffer();
        });
    }

    end(chunk, encoding, callback) {
        if (typeof chunk === 'function') { callback = chunk; chunk = undefined; encoding = undefined; }
        if (typeof encoding === 'function') { callback = encoding; encoding = undefined; }
        if (this._ending) return this;
        if (chunk !== undefined && chunk !== null) {
            this.write(chunk, encoding);
        }
        this._ending = true;
        this.writableEnded = true;
        if (callback) this.once('finish', callback);
        if (!this._writing && this._wBuffer.length === 0) {
            this._finishWrite();
        }
        return this;
    }

    _finishWrite() {
        if (this._finished) return;
        this._final((err) => {
            if (err) {
                this.emit('error', err);
                return;
            }
            this._finished = true;
            this.writable = false;
            this.writableFinished = true;
            this.emit('finish');
        });
    }

    cork() { this._corked++; }
    uncork() {
        if (this._corked > 0) this._corked--;
        if (this._corked === 0 && !this._writing) this._clearWBuffer();
    }

    destroy(err) {
        if (this._destroyed) return this;
        this._destroyed = true;
        this._wDestroyed = true;
        this.readable = false;
        this.writable = false;
        this._buffer.length = 0;
        this._bufferSize = 0;
        this._wBuffer.length = 0;
        this._wBufferSize = 0;
        const destroyFn = this._destroy || ((e, cb) => cb(e));
        destroyFn.call(this, err || null, (e) => {
            if (e) this.emit('error', e);
            this.emit('close');
        });
        return this;
    }
}


// --- Transform ---

export class Transform extends Duplex {
    constructor(opts) {
        super(opts);
        if (typeof (opts && opts.transform) === 'function') this._transform = opts.transform;
        if (typeof (opts && opts.flush) === 'function') this._flush = opts.flush;
        this._transforming = false;
        this._flushed = false;
    }

    // Override point
    _transform(chunk, encoding, callback) {
        callback(null, chunk);
    }

    _flush(callback) {
        callback();
    }

    _write(chunk, encoding, callback) {
        this._transforming = true;
        this._transform(chunk, encoding, (err, data) => {
            this._transforming = false;
            if (err) return callback(err);
            if (data !== undefined && data !== null) {
                this.push(data);
            }
            callback();
        });
    }

    _finishWrite() {
        if (this._finished || this._flushed) return;
        this._flushed = true;
        this._flush((err, data) => {
            if (err) {
                this.emit('error', err);
                return;
            }
            if (data !== undefined && data !== null) {
                this.push(data);
            }
            this.push(null);
            this._finished = true;
            this.writable = false;
            this.writableFinished = true;
            this.emit('finish');
        });
    }
}


// --- PassThrough ---

export class PassThrough extends Transform {
    constructor(opts) {
        super(opts);
    }
    _transform(chunk, _encoding, callback) {
        callback(null, chunk);
    }
}


// --- pipeline ---

export function pipeline(...args) {
    let callback;
    if (typeof args[args.length - 1] === 'function') {
        callback = args.pop();
    }

    if (args.length < 2) {
        throw new Error('pipeline requires at least 2 streams');
    }

    const streams = args;
    let error;

    const onError = (err) => {
        if (!error) {
            error = err;
            for (const s of streams) {
                if (typeof s.destroy === 'function') s.destroy();
            }
            if (callback) callback(err);
        }
    };

    for (let i = 0; i < streams.length - 1; i++) {
        streams[i].pipe(streams[i + 1]);
        streams[i].on('error', onError);
    }
    // Last stream error
    streams[streams.length - 1].on('error', onError);

    // On finish of last stream
    const last = streams[streams.length - 1];
    if (last instanceof Writable || last instanceof Duplex) {
        last.on('finish', () => {
            if (!error && callback) callback();
        });
    } else {
        last.on('end', () => {
            if (!error && callback) callback();
        });
    }

    return last;
}

// Re-export EventEmitter-based stream classes
export default {
    Readable,
    Writable,
    Duplex,
    Transform,
    PassThrough,
    pipeline,
    Stream: EventEmitter,
};
