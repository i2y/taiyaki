// Node.js Buffer polyfill — ES module version.
// The Buffer class is defined in buffer_global.js (eval'd eagerly).
// This module re-exports it for `import { Buffer } from 'buffer'`.

export const Buffer = globalThis.Buffer;
export default Buffer;
