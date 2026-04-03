// bun:sqlite compatible API
// Host functions: __sqlite_open, __sqlite_close, __sqlite_exec, __sqlite_run, __sqlite_all, __sqlite_get, __sqlite_values

export class Statement {
    constructor(db, sql) {
        this._db = db;
        this._sql = sql;
    }

    _params(args) {
        if (args.length === 1 && typeof args[0] === 'object' && args[0] !== null && !Array.isArray(args[0])) {
            return JSON.stringify(Object.values(args[0]));
        }
        return JSON.stringify(args);
    }

    all(...params) {
        return JSON.parse(__sqlite_all(String(this._db._id), this._sql, this._params(params)));
    }

    get(...params) {
        var r = __sqlite_get(String(this._db._id), this._sql, this._params(params));
        return JSON.parse(r);
    }

    run(...params) {
        return JSON.parse(__sqlite_run(String(this._db._id), this._sql, this._params(params)));
    }

    values(...params) {
        return JSON.parse(__sqlite_values(String(this._db._id), this._sql, this._params(params)));
    }
}

export class Database {
    constructor(path) {
        if (typeof __sqlite_open === 'undefined') {
            throw new Error('SQLite is not available. Build with --features sqlite');
        }
        path = path !== undefined ? String(path) : ':memory:';
        var result = JSON.parse(__sqlite_open(path));
        this._id = result.id;
        this._closed = false;
    }

    close() {
        if (!this._closed) {
            this._closed = true;
            __sqlite_close(String(this._id));
        }
    }

    exec(sql) {
        if (this._closed) throw new Error('Database is closed');
        __sqlite_exec(String(this._id), sql);
    }

    run(sql, ...params) {
        if (this._closed) throw new Error('Database is closed');
        return JSON.parse(__sqlite_run(String(this._id), sql, JSON.stringify(params)));
    }

    query(sql) {
        if (this._closed) throw new Error('Database is closed');
        return new Statement(this, sql);
    }

    prepare(sql) {
        return this.query(sql);
    }
}
