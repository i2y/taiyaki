// Sets globalThis.Buffer — evaluated eagerly (not as ES module).
// Uses __buffer_from_string, __buffer_to_string, __buffer_b64_to_bytes,
// __buffer_bytes_to_b64 host functions (registered before this runs).

(function() {
    function _b64ToBytes(b64) {
        return new Uint8Array(__buffer_b64_to_bytes(b64));
    }
    function _bytesToB64(uint8arr) {
        return __buffer_bytes_to_b64(JSON.stringify(Array.from(uint8arr)));
    }

    class Buffer extends Uint8Array {
        static alloc(size, fill, encoding) {
            const buf = new Buffer(size);
            if (fill !== undefined) {
                if (typeof fill === 'number') buf.fill(fill);
                else if (typeof fill === 'string') {
                    const src = Buffer.from(fill, encoding);
                    for (let i = 0; i < size; i++) buf[i] = src[i % src.length];
                }
            }
            return buf;
        }
        static allocUnsafe(size) { return new Buffer(size); }
        static from(value, encodingOrOffset, length) {
            if (typeof value === 'string') {
                const encoding = encodingOrOffset || 'utf-8';
                const b64 = __buffer_from_string(value, encoding);
                return new Buffer(_b64ToBytes(b64));
            }
            if (value instanceof ArrayBuffer) {
                const offset = encodingOrOffset || 0;
                const len = length !== undefined ? length : value.byteLength - offset;
                const buf = new Buffer(len);
                buf.set(new Uint8Array(value, offset, len));
                return buf;
            }
            if (ArrayBuffer.isView(value) || Array.isArray(value)) {
                const buf = new Buffer(value.length);
                for (let i = 0; i < value.length; i++) buf[i] = value[i] & 0xff;
                return buf;
            }
            if (value instanceof Buffer) {
                const buf = new Buffer(value.length);
                buf.set(value);
                return buf;
            }
            throw new TypeError('Invalid argument for Buffer.from');
        }
        static isBuffer(obj) { return obj instanceof Buffer; }
        static isEncoding(enc) {
            return ['utf-8','utf8','ascii','latin1','binary','hex','base64','ucs2','ucs-2','utf16le','utf-16le'].includes(String(enc).toLowerCase());
        }
        static byteLength(str, enc) {
            if (typeof str !== 'string') return str.length || 0;
            return Buffer.from(str, enc).length;
        }
        static concat(list, totalLength) {
            if (list.length === 0) return Buffer.alloc(0);
            if (totalLength === undefined) { totalLength = 0; for (const b of list) totalLength += b.length; }
            const result = Buffer.alloc(totalLength);
            let offset = 0;
            for (const buf of list) { result.set(buf, offset); offset += buf.length; if (offset >= totalLength) break; }
            return result;
        }
        static compare(a, b) {
            const len = Math.min(a.length, b.length);
            for (let i = 0; i < len; i++) { if (a[i] < b[i]) return -1; if (a[i] > b[i]) return 1; }
            if (a.length < b.length) return -1;
            if (a.length > b.length) return 1;
            return 0;
        }
        toString(encoding, start, end) {
            encoding = encoding || 'utf-8'; start = start || 0; end = end !== undefined ? end : this.length;
            const slice = this.subarray(start, end);
            return __buffer_to_string(_bytesToB64(slice), encoding);
        }
        toJSON() { return { type: 'Buffer', data: Array.from(this) }; }
        equals(other) {
            if (this.length !== other.length) return false;
            for (let i = 0; i < this.length; i++) if (this[i] !== other[i]) return false;
            return true;
        }
        compare(target, ts, te, ss, se) {
            ts = ts||0; te = te !== undefined ? te : target.length; ss = ss||0; se = se !== undefined ? se : this.length;
            return Buffer.compare(this.subarray(ss, se), target.subarray(ts, te));
        }
        copy(target, targetStart, sourceStart, sourceEnd) {
            targetStart = targetStart||0; sourceStart = sourceStart||0; sourceEnd = sourceEnd !== undefined ? sourceEnd : this.length;
            const toCopy = this.subarray(sourceStart, sourceEnd);
            const len = Math.min(toCopy.length, target.length - targetStart);
            for (let i = 0; i < len; i++) target[targetStart + i] = toCopy[i];
            return len;
        }
        slice(start, end) { const s = super.slice(start, end); const buf = new Buffer(s.length); buf.set(s); return buf; }
        readUInt8(o) { return this[o]; }
        readInt8(o) { return this[o] | (this[o] & 0x80 ? 0xffffff00 : 0); }
        readUInt16BE(o) { return (this[o] << 8) | this[o+1]; }
        readUInt16LE(o) { return this[o] | (this[o+1] << 8); }
        readInt16BE(o) { const v = this.readUInt16BE(o); return v & 0x8000 ? v | 0xffff0000 : v; }
        readInt16LE(o) { const v = this.readUInt16LE(o); return v & 0x8000 ? v | 0xffff0000 : v; }
        readUInt32BE(o) { return ((this[o]*0x1000000)+(this[o+1]<<16)+(this[o+2]<<8)+this[o+3])>>>0; }
        readUInt32LE(o) { return ((this[o+3]*0x1000000)+(this[o+2]<<16)+(this[o+1]<<8)+this[o])>>>0; }
        readInt32BE(o) { return (this[o]<<24)|(this[o+1]<<16)|(this[o+2]<<8)|this[o+3]; }
        readInt32LE(o) { return (this[o+3]<<24)|(this[o+2]<<16)|(this[o+1]<<8)|this[o]; }
        readFloatBE(o) { return new DataView(this.buffer, this.byteOffset+o, 4).getFloat32(0, false); }
        readFloatLE(o) { return new DataView(this.buffer, this.byteOffset+o, 4).getFloat32(0, true); }
        readDoubleBE(o) { return new DataView(this.buffer, this.byteOffset+o, 8).getFloat64(0, false); }
        readDoubleLE(o) { return new DataView(this.buffer, this.byteOffset+o, 8).getFloat64(0, true); }
        writeUInt8(v, o) { this[o] = v&0xff; return o+1; }
        writeInt8(v, o) { this[o] = v&0xff; return o+1; }
        writeUInt16BE(v, o) { this[o]=(v>>>8)&0xff; this[o+1]=v&0xff; return o+2; }
        writeUInt16LE(v, o) { this[o]=v&0xff; this[o+1]=(v>>>8)&0xff; return o+2; }
        writeUInt32BE(v, o) { this[o]=(v>>>24)&0xff; this[o+1]=(v>>>16)&0xff; this[o+2]=(v>>>8)&0xff; this[o+3]=v&0xff; return o+4; }
        writeUInt32LE(v, o) { this[o]=v&0xff; this[o+1]=(v>>>8)&0xff; this[o+2]=(v>>>16)&0xff; this[o+3]=(v>>>24)&0xff; return o+4; }
        writeFloatBE(v, o) { new DataView(this.buffer, this.byteOffset+o, 4).setFloat32(0, v, false); return o+4; }
        writeFloatLE(v, o) { new DataView(this.buffer, this.byteOffset+o, 4).setFloat32(0, v, true); return o+4; }
        writeDoubleBE(v, o) { new DataView(this.buffer, this.byteOffset+o, 8).setFloat64(0, v, false); return o+8; }
        writeDoubleLE(v, o) { new DataView(this.buffer, this.byteOffset+o, 8).setFloat64(0, v, true); return o+8; }
        write(string, offset, length, encoding) {
            offset = offset||0; encoding = encoding||'utf-8';
            const src = Buffer.from(string, encoding);
            const maxLen = length !== undefined ? Math.min(length, src.length) : src.length;
            const toCopy = Math.min(maxLen, this.length - offset);
            for (let i = 0; i < toCopy; i++) this[offset + i] = src[i];
            return toCopy;
        }
        includes(value, byteOffset, encoding) { return this.indexOf(value, byteOffset, encoding) !== -1; }
        indexOf(value, byteOffset, encoding) {
            byteOffset = byteOffset||0;
            if (typeof value === 'number') {
                for (let i = byteOffset; i < this.length; i++) if (this[i] === (value&0xff)) return i;
                return -1;
            }
            const needle = typeof value === 'string' ? Buffer.from(value, encoding||'utf-8') : value;
            for (let i = byteOffset; i <= this.length - needle.length; i++) {
                let found = true;
                for (let j = 0; j < needle.length; j++) { if (this[i+j] !== needle[j]) { found = false; break; } }
                if (found) return i;
            }
            return -1;
        }
    }

    globalThis.Buffer = Buffer;
})();
