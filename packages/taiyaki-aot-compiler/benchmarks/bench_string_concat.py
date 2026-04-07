def string_concat(n):
    result = ""
    i = 0
    while i < n:
        result = result + "a"
        i += 1
    return len(result)

length = string_concat(100000)
print(length)
