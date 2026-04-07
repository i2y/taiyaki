function arraySum(n) {
  const arr = [];
  let i = 0;
  while (i < n) {
    arr.push(i);
    i = i + 1;
  }
  let sum = 0;
  let j = 0;
  while (j < n) {
    sum = sum + arr[j];
    j = j + 1;
  }
  return sum;
}

console.log(arraySum(1000000));
