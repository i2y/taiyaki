import { join, dirname, basename, extname, resolve, relative, parse, sep } from 'path';

console.log('=== path module ===');
console.log('join:', join('/usr', 'local', 'bin'));
console.log('dirname:', dirname('/home/user/file.txt'));
console.log('basename:', basename('/home/user/file.txt'));
console.log('extname:', extname('archive.tar.gz'));
console.log('resolve:', resolve('/foo', 'bar', 'baz'));
console.log('relative:', relative('/data/a/b', '/data/c/d'));
console.log('parse:', JSON.stringify(parse('/home/user/file.txt')));
console.log('sep:', sep);
