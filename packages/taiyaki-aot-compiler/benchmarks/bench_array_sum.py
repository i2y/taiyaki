def array_sum(n):
    arr = []
    i = 0
    while i < n:
        arr.append(i)
        i += 1
    s = 0
    j = 0
    while j < n:
        s = s + arr[j]
        j += 1
    return s

result = array_sum(1000000)
print(result)
