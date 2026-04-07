function sieve(limit) {
  const arr = [];
  let i = 0;
  while (i <= limit) {
    arr.push(1);
    i = i + 1;
  }
  arr[0] = 0;
  arr[1] = 0;
  let p = 2;
  while (p * p <= limit) {
    if (arr[p] === 1) {
      let m = p * p;
      while (m <= limit) {
        arr[m] = 0;
        m = m + p;
      }
    }
    p = p + 1;
  }
  let count = 0;
  let j = 0;
  while (j <= limit) {
    if (arr[j] === 1) {
      count = count + 1;
    }
    j = j + 1;
  }
  return count;
}

console.log(sieve(1000000));
