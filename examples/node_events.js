import { EventEmitter } from 'events';

console.log('=== events module ===');

const ee = new EventEmitter();

ee.on('data', (msg) => console.log('received:', msg));
ee.once('close', () => console.log('connection closed'));

ee.emit('data', 'hello');
ee.emit('data', 'world');
ee.emit('close');
ee.emit('close'); // should not fire again

console.log('listener count:', ee.listenerCount('data'));
console.log('event names:', ee.eventNames());
