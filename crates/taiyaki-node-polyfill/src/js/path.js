// POSIX path module (path-browserify style)
// No Windows support — POSIX only for embedded use.

const CHAR_FORWARD_SLASH = 47; // '/'
const CHAR_DOT = 46; // '.'

function normalizeStringPosix(path, allowAboveRoot) {
    let res = '';
    let lastSegmentLength = 0;
    let lastSlash = -1;
    let dots = 0;
    let code;
    for (let i = 0; i <= path.length; ++i) {
        if (i < path.length) code = path.charCodeAt(i);
        else if (code === CHAR_FORWARD_SLASH) break;
        else code = CHAR_FORWARD_SLASH;

        if (code === CHAR_FORWARD_SLASH) {
            if (lastSlash === i - 1 || dots === 1) {
                // NOOP
            } else if (lastSlash !== i - 1 && dots === 2) {
                if (
                    res.length < 2 ||
                    lastSegmentLength !== 2 ||
                    res.charCodeAt(res.length - 1) !== CHAR_DOT ||
                    res.charCodeAt(res.length - 2) !== CHAR_DOT
                ) {
                    if (res.length > 2) {
                        const lastSlashIndex = res.lastIndexOf('/');
                        if (lastSlashIndex !== res.length - 1) {
                            if (lastSlashIndex === -1) {
                                res = '';
                                lastSegmentLength = 0;
                            } else {
                                res = res.slice(0, lastSlashIndex);
                                lastSegmentLength = res.length - 1 - res.lastIndexOf('/');
                            }
                            lastSlash = i;
                            dots = 0;
                            continue;
                        }
                    } else if (res.length === 2 || res.length === 1) {
                        res = '';
                        lastSegmentLength = 0;
                        lastSlash = i;
                        dots = 0;
                        continue;
                    }
                }
                if (allowAboveRoot) {
                    if (res.length > 0) res += '/..';
                    else res = '..';
                    lastSegmentLength = 2;
                }
            } else {
                if (res.length > 0) res += '/' + path.slice(lastSlash + 1, i);
                else res = path.slice(lastSlash + 1, i);
                lastSegmentLength = i - lastSlash - 1;
            }
            lastSlash = i;
            dots = 0;
        } else if (code === CHAR_DOT && dots !== -1) {
            ++dots;
        } else {
            dots = -1;
        }
    }
    return res;
}

export function normalize(path) {
    if (path.length === 0) return '.';
    const isAbsoluteVal = path.charCodeAt(0) === CHAR_FORWARD_SLASH;
    const trailingSeparator = path.charCodeAt(path.length - 1) === CHAR_FORWARD_SLASH;
    let out = normalizeStringPosix(path, !isAbsoluteVal);
    if (out.length === 0 && !isAbsoluteVal) out = '.';
    if (out.length > 0 && trailingSeparator) out += '/';
    if (isAbsoluteVal) return '/' + out;
    return out;
}

export function isAbsolute(path) {
    return path.length > 0 && path.charCodeAt(0) === CHAR_FORWARD_SLASH;
}

export function join(...args) {
    if (args.length === 0) return '.';
    let joined;
    for (let i = 0; i < args.length; ++i) {
        const arg = args[i];
        if (arg.length > 0) {
            if (joined === undefined) joined = arg;
            else joined += '/' + arg;
        }
    }
    if (joined === undefined) return '.';
    return normalize(joined);
}

export function resolve(...args) {
    let resolvedPath = '';
    let resolvedAbsolute = false;
    let cwd;

    for (let i = args.length - 1; i >= -1 && !resolvedAbsolute; i--) {
        let path;
        if (i >= 0) {
            path = args[i];
        } else {
            if (cwd === undefined) {
                cwd = typeof __path_cwd === 'function' ? __path_cwd() : '/';
            }
            path = cwd;
        }
        if (path.length === 0) continue;
        resolvedPath = path + '/' + resolvedPath;
        resolvedAbsolute = path.charCodeAt(0) === CHAR_FORWARD_SLASH;
    }

    resolvedPath = normalizeStringPosix(resolvedPath, !resolvedAbsolute);

    if (resolvedAbsolute) {
        if (resolvedPath.length > 0) return '/' + resolvedPath;
        else return '/';
    } else if (resolvedPath.length > 0) {
        return resolvedPath;
    } else {
        return '.';
    }
}

export function relative(from, to) {
    if (from === to) return '';

    from = resolve(from);
    to = resolve(to);

    if (from === to) return '';

    let fromStart = 1;
    for (; fromStart < from.length; ++fromStart) {
        if (from.charCodeAt(fromStart) !== CHAR_FORWARD_SLASH) break;
    }
    const fromEnd = from.length;
    const fromLen = fromEnd - fromStart;

    let toStart = 1;
    for (; toStart < to.length; ++toStart) {
        if (to.charCodeAt(toStart) !== CHAR_FORWARD_SLASH) break;
    }
    const toEnd = to.length;
    const toLen = toEnd - toStart;

    const length = fromLen < toLen ? fromLen : toLen;
    let lastCommonSep = -1;
    let i = 0;
    for (; i <= length; ++i) {
        if (i === length) {
            if (toLen > length) {
                if (to.charCodeAt(toStart + i) === CHAR_FORWARD_SLASH) {
                    return to.slice(toStart + i + 1);
                } else if (i === 0) {
                    return to.slice(toStart + i);
                }
            } else if (fromLen > length) {
                if (from.charCodeAt(fromStart + i) === CHAR_FORWARD_SLASH) {
                    lastCommonSep = i;
                } else if (i === 0) {
                    lastCommonSep = 0;
                }
            }
            break;
        }
        const fromCode = from.charCodeAt(fromStart + i);
        const toCode = to.charCodeAt(toStart + i);
        if (fromCode !== toCode) break;
        else if (fromCode === CHAR_FORWARD_SLASH) lastCommonSep = i;
    }

    let out = '';
    for (i = fromStart + lastCommonSep + 1; i <= fromEnd; ++i) {
        if (i === fromEnd || from.charCodeAt(i) === CHAR_FORWARD_SLASH) {
            if (out.length === 0) out += '..';
            else out += '/..';
        }
    }

    if (out.length > 0) return out + to.slice(toStart + lastCommonSep);
    else {
        toStart += lastCommonSep;
        if (to.charCodeAt(toStart) === CHAR_FORWARD_SLASH) ++toStart;
        return to.slice(toStart);
    }
}

export function dirname(path) {
    if (path.length === 0) return '.';
    let code = path.charCodeAt(0);
    const hasRoot = code === CHAR_FORWARD_SLASH;
    let end = -1;
    let matchedSlash = true;
    for (let i = path.length - 1; i >= 1; --i) {
        code = path.charCodeAt(i);
        if (code === CHAR_FORWARD_SLASH) {
            if (!matchedSlash) {
                end = i;
                break;
            }
        } else {
            matchedSlash = false;
        }
    }
    if (end === -1) return hasRoot ? '/' : '.';
    if (hasRoot && end === 1) return '//';
    return path.slice(0, end);
}

export function basename(path, ext) {
    let start = 0;
    let end = -1;
    let matchedSlash = true;
    let i;

    if (ext !== undefined && ext.length > 0 && ext.length <= path.length) {
        if (ext.length === path.length && ext === path) return '';
        let extIdx = ext.length - 1;
        let firstNonSlashEnd = -1;
        for (i = path.length - 1; i >= 0; --i) {
            const code = path.charCodeAt(i);
            if (code === CHAR_FORWARD_SLASH) {
                if (!matchedSlash) {
                    start = i + 1;
                    break;
                }
            } else {
                if (firstNonSlashEnd === -1) {
                    matchedSlash = false;
                    firstNonSlashEnd = i + 1;
                }
                if (extIdx >= 0) {
                    if (code === ext.charCodeAt(extIdx)) {
                        if (--extIdx === -1) {
                            end = i;
                        }
                    } else {
                        extIdx = -1;
                        end = firstNonSlashEnd;
                    }
                }
            }
        }
        if (start === end) end = firstNonSlashEnd;
        else if (end === -1) end = path.length;
        return path.slice(start, end);
    } else {
        for (i = path.length - 1; i >= 0; --i) {
            if (path.charCodeAt(i) === CHAR_FORWARD_SLASH) {
                if (!matchedSlash) {
                    start = i + 1;
                    break;
                }
            } else if (end === -1) {
                matchedSlash = false;
                end = i + 1;
            }
        }
        if (end === -1) return '';
        return path.slice(start, end);
    }
}

export function extname(path) {
    let startDot = -1;
    let startPart = 0;
    let end = -1;
    let matchedSlash = true;
    let preDotState = 0;
    for (let i = path.length - 1; i >= 0; --i) {
        const code = path.charCodeAt(i);
        if (code === CHAR_FORWARD_SLASH) {
            if (!matchedSlash) {
                startPart = i + 1;
                break;
            }
            continue;
        }
        if (end === -1) {
            matchedSlash = false;
            end = i + 1;
        }
        if (code === CHAR_DOT) {
            if (startDot === -1) startDot = i;
            else if (preDotState !== 1) preDotState = 1;
        } else if (startDot !== -1) {
            preDotState = -1;
        }
    }
    if (
        startDot === -1 ||
        end === -1 ||
        preDotState === 0 ||
        (preDotState === 1 && startDot === end - 1 && startDot === startPart + 1)
    ) {
        return '';
    }
    return path.slice(startDot, end);
}

export function parse(path) {
    const ret = { root: '', dir: '', base: '', ext: '', name: '' };
    if (path.length === 0) return ret;
    let code = path.charCodeAt(0);
    const isAbsoluteVal = code === CHAR_FORWARD_SLASH;
    let start;
    if (isAbsoluteVal) {
        ret.root = '/';
        start = 1;
    } else {
        start = 0;
    }
    let startDot = -1;
    let startPart = 0;
    let end = -1;
    let matchedSlash = true;
    let i = path.length - 1;
    let preDotState = 0;

    for (; i >= start; --i) {
        code = path.charCodeAt(i);
        if (code === CHAR_FORWARD_SLASH) {
            if (!matchedSlash) {
                startPart = i + 1;
                break;
            }
            continue;
        }
        if (end === -1) {
            matchedSlash = false;
            end = i + 1;
        }
        if (code === CHAR_DOT) {
            if (startDot === -1) startDot = i;
            else if (preDotState !== 1) preDotState = 1;
        } else if (startDot !== -1) {
            preDotState = -1;
        }
    }

    if (
        startDot === -1 ||
        end === -1 ||
        preDotState === 0 ||
        (preDotState === 1 && startDot === end - 1 && startDot === startPart + 1)
    ) {
        if (end !== -1) {
            if (startPart === 0 && isAbsoluteVal) {
                ret.base = ret.name = path.slice(1, end);
            } else {
                ret.base = ret.name = path.slice(startPart, end);
            }
        }
    } else {
        if (startPart === 0 && isAbsoluteVal) {
            ret.name = path.slice(1, startDot);
            ret.base = path.slice(1, end);
        } else {
            ret.name = path.slice(startPart, startDot);
            ret.base = path.slice(startPart, end);
        }
        ret.ext = path.slice(startDot, end);
    }

    if (startPart > 0) ret.dir = path.slice(0, startPart - 1);
    else if (isAbsoluteVal) ret.dir = '/';

    return ret;
}

export function format(pathObject) {
    const dir = pathObject.dir || pathObject.root;
    const base = pathObject.base || (pathObject.name || '') + (pathObject.ext || '');
    if (!dir) return base;
    if (dir === pathObject.root) return dir + base;
    return dir + '/' + base;
}

export const sep = '/';
export const delimiter = ':';

const posix = {
    normalize,
    isAbsolute,
    join,
    resolve,
    relative,
    dirname,
    basename,
    extname,
    parse,
    format,
    sep,
    delimiter,
};

export { posix };
export const win32 = null;

export default posix;
