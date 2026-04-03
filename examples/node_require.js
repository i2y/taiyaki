// Test require() with a relative file
import { join, dirname } from 'path';

console.log('=== require() ===');

// Test that require is available
console.log('require exists:', typeof require === 'function');
console.log('require.resolve exists:', typeof require.resolve === 'function');

// Note: to test full require() with relative files, you'd need
// actual files on disk. This example tests the global availability.
console.log('module exists:', typeof module === 'object');
console.log('exports exists:', typeof exports === 'object');
