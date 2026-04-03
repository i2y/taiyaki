import { EventEmitter } from 'events';

export function readFileSync(path, options) {
    const encoding = typeof options === 'string' ? options : (options && options.encoding);
    return __fs_read_file_sync(String(path), encoding || 'utf8');
}

export function writeFileSync(path, data, options) {
    const encoding = typeof options === 'string' ? options : (options && options.encoding) || 'utf8';
    __fs_write_file_sync(String(path), String(data), encoding);
}

export function existsSync(path) {
    return __fs_exists_sync(String(path));
}

export function mkdirSync(path, options) {
    const recursive = (typeof options === 'object' && options !== null) ? !!options.recursive : false;
    __fs_mkdir_sync(String(path), recursive);
}

export function readdirSync(path, _options) {
    return JSON.parse(__fs_readdir_sync(String(path)));
}

function makeStats(json) {
    const s = JSON.parse(json);
    return {
        dev: s.dev,
        ino: s.ino,
        mode: s.mode,
        nlink: s.nlink,
        uid: s.uid,
        gid: s.gid,
        size: s.size,
        atimeMs: s.atime,
        mtimeMs: s.mtime,
        ctimeMs: s.ctime,
        birthtimeMs: s.ctime,
        atime: new Date(s.atime),
        mtime: new Date(s.mtime),
        ctime: new Date(s.ctime),
        birthtime: new Date(s.ctime),
        isFile: () => s.isFile,
        isDirectory: () => s.isDir,
        isSymbolicLink: () => s.isSymlink,
        isBlockDevice: () => false,
        isCharacterDevice: () => false,
        isFIFO: () => false,
        isSocket: () => false,
    };
}

export function statSync(path, _options) {
    return makeStats(__fs_stat_sync(String(path)));
}

export function lstatSync(path, _options) {
    return makeStats(__fs_lstat_sync(String(path)));
}

export function unlinkSync(path) {
    __fs_unlink_sync(String(path));
}

export function renameSync(oldPath, newPath) {
    __fs_rename_sync(String(oldPath), String(newPath));
}

export function rmSync(path, options) {
    const recursive = (options && options.recursive) ? true : false;
    const force = (options && options.force) ? true : false;
    __fs_rm_sync(String(path), recursive, force);
}

export function copyFileSync(src, dest) {
    __fs_copy_file_sync(String(src), String(dest));
}

export function appendFileSync(path, data, _options) {
    __fs_append_file_sync(String(path), String(data));
}

export function realpathSync(path) {
    return __fs_realpath_sync(String(path));
}

export function chmodSync(path, mode) {
    __fs_chmod_sync(String(path), mode);
}

// promises namespace — uses true async (tokio::fs) when available, else wraps sync
const _hasAsync = typeof __fs_read_file_async !== 'undefined';

function _asyncReadFile(path, opts) {
    const encoding = typeof opts === 'string' ? opts : (opts && opts.encoding) || 'utf8';
    return __fs_read_file_async(String(path), encoding);
}
function _asyncWriteFile(path, data) {
    return __fs_write_file_async(String(path), String(data)).then(() => undefined);
}
function _asyncStat(path) {
    return __fs_stat_async(String(path)).then(makeStats);
}
function _asyncLstat(path) {
    return __fs_lstat_async(String(path)).then(makeStats);
}
function _asyncReaddir(path) {
    return __fs_readdir_async(String(path)).then(JSON.parse);
}
function _asyncMkdir(path, opts) {
    const recursive = (typeof opts === 'object' && opts !== null) ? !!opts.recursive : false;
    return __fs_mkdir_async(String(path), recursive).then(() => undefined);
}
function _asyncUnlink(path) {
    return __fs_unlink_async(String(path)).then(() => undefined);
}
function _asyncRename(oldP, newP) {
    return __fs_rename_async(String(oldP), String(newP)).then(() => undefined);
}
function _asyncRm(path, opts) {
    const recursive = (opts && opts.recursive) ? true : false;
    const force = (opts && opts.force) ? true : false;
    return __fs_rm_async(String(path), recursive, force).then(() => undefined);
}
function _asyncCopyFile(src, dest) {
    return __fs_copy_file_async(String(src), String(dest)).then(() => undefined);
}
function _asyncAppendFile(path, data) {
    return __fs_append_file_async(String(path), String(data)).then(() => undefined);
}
function _asyncRealpath(path) {
    return __fs_realpath_async(String(path));
}
function _asyncChmod(path, mode) {
    return __fs_chmod_async(String(path), mode).then(() => undefined);
}

export const promises = {
    readFile: _hasAsync ? _asyncReadFile : (path, opts) => Promise.resolve().then(() => readFileSync(path, opts)),
    writeFile: _hasAsync ? _asyncWriteFile : (path, data, opts) => Promise.resolve().then(() => writeFileSync(path, data, opts)),
    mkdir: _hasAsync ? _asyncMkdir : (path, opts) => Promise.resolve().then(() => mkdirSync(path, opts)),
    readdir: _hasAsync ? _asyncReaddir : (path, opts) => Promise.resolve().then(() => readdirSync(path, opts)),
    stat: _hasAsync ? _asyncStat : (path) => Promise.resolve().then(() => statSync(path)),
    lstat: _hasAsync ? _asyncLstat : (path) => Promise.resolve().then(() => lstatSync(path)),
    unlink: _hasAsync ? _asyncUnlink : (path) => Promise.resolve().then(() => unlinkSync(path)),
    rename: _hasAsync ? _asyncRename : (oldP, newP) => Promise.resolve().then(() => renameSync(oldP, newP)),
    rm: _hasAsync ? _asyncRm : (path, opts) => Promise.resolve().then(() => rmSync(path, opts)),
    copyFile: _hasAsync ? _asyncCopyFile : (src, dest) => Promise.resolve().then(() => copyFileSync(src, dest)),
    appendFile: _hasAsync ? _asyncAppendFile : (path, data) => Promise.resolve().then(() => appendFileSync(path, data)),
    realpath: _hasAsync ? _asyncRealpath : (path) => Promise.resolve().then(() => realpathSync(path)),
    chmod: _hasAsync ? _asyncChmod : (path, mode) => Promise.resolve().then(() => chmodSync(path, mode)),
};

let watch;

if (typeof __fs_watch_start !== 'undefined') {
    class FSWatcher extends EventEmitter {
        constructor(id) {
            super();
            this._id = id;
            this._closed = false;
            this._poll();
        }
        async _poll() {
            while (!this._closed) {
                let evJSON;
                try {
                    evJSON = await __fs_watch_poll(this._id);
                } catch (_) { break; }
                if (!evJSON || this._closed) break;
                try {
                    const ev = JSON.parse(evJSON);
                    this.emit('change', ev.eventType, ev.filename);
                } catch (_) { break; }
            }
        }
        close() {
            if (this._closed) return;
            this._closed = true;
            try { __fs_watch_close(this._id); } catch (_) {}
            this.emit('close');
        }
        ref() { return this; }
        unref() { return this; }
    }

    watch = function _watch(path, optionsOrCb, maybeCb) {
        let options = {}, callback;
        if (typeof optionsOrCb === 'function') {
            callback = optionsOrCb;
        } else {
            options = optionsOrCb || {};
            callback = maybeCb;
        }
        const recursive = !!options.recursive;
        const watcherId = __fs_watch_start(String(path), recursive);
        const watcher = new FSWatcher(watcherId);
        if (typeof callback === 'function') {
            watcher.on('change', callback);
        }
        return watcher;
    };
}

export { watch };

export default {
    readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync,
    statSync, lstatSync, unlinkSync, renameSync, rmSync, copyFileSync,
    appendFileSync, realpathSync, chmodSync, promises, watch,
};
