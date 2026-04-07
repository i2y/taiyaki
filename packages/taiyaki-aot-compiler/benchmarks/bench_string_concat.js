function stringConcat(n) {
  let result = "";
  let i = 0;
  while (i < n) {
    result = result + "a";
    i = i + 1;
  }
  return result.length;
}

console.log(stringConcat(100000));
