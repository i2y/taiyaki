console.log('=== Buffer module ===');

const buf1 = Buffer.from('Hello World');
console.log('from string:', buf1.toString());
console.log('length:', buf1.length);
console.log('hex:', buf1.toString('hex'));

const buf2 = Buffer.alloc(4, 0xab);
console.log('alloc:', buf2[0].toString(16), buf2[3].toString(16));

const concat = Buffer.concat([Buffer.from('foo'), Buffer.from('bar')]);
console.log('concat:', concat.toString());

const num = Buffer.alloc(4);
num.writeUInt32BE(0xdeadbeef, 0);
console.log('u32be:', num.readUInt32BE(0).toString(16));

console.log('isBuffer:', Buffer.isBuffer(buf1));
console.log('byteLength:', Buffer.byteLength('hello'));
console.log('includes:', buf1.includes('World'));
