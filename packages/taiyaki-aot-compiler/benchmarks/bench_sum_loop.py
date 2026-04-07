def sum_loop(n):
    s = 0
    i = 0
    while i < n:
        s = s + i
        i = i + 1
    return s

result = sum_loop(10000000)
print(result)
