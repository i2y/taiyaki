import ts

rt = ts.Runtime()

# JavaScript 評価
result = rt.eval("1 + 2")
print(f"JS: 1 + 2 = {result}")

# TypeScript 評価
result = rt.eval_ts("const x: number = 42; x")
print(f"TS: const x: number = 42; x => {result}")

# 文字列
result = rt.eval("'hello' + ' from libts'")
print(f"JS: 'hello' + ' from libts' => {result}")

# オブジェクト (JSON として返される → Python dict に変換)
result = rt.eval("({name: 'Alice', age: 30})")
print(f"JS: object => {result} (type: {type(result).__name__})")

# 配列
result = rt.eval("[1, 2, 3]")
print(f"JS: array => {result} (type: {type(result).__name__})")

# 真偽値
result = rt.eval("true")
print(f"JS: true => {result} (type: {type(result).__name__})")

# TypeScript インターフェース
result = rt.eval_ts("""
    interface User { name: string; age: number }
    const user: User = { name: "Bob", age: 25 };
    user.name
""")
print(f"TS: interface + object => {result}")

print("\nAll examples passed!")
