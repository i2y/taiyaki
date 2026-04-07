def sieve(limit):
    arr = [1] * (limit + 1)
    arr[0] = 0
    arr[1] = 0
    p = 2
    while p * p <= limit:
        if arr[p] == 1:
            m = p * p
            while m <= limit:
                arr[m] = 0
                m += p
        p += 1
    count = 0
    j = 0
    while j <= limit:
        if arr[j] == 1:
            count += 1
        j += 1
    return count

result = sieve(1000000)
print(result)
