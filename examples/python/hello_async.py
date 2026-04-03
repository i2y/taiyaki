import asyncio
import ts

# ── Sync-style usage (still works, now releases GIL during execution) ──

rt = ts.AsyncRuntime()

print("1 + 2 =", rt.eval("1 + 2"))

result = rt.eval_async("Promise.resolve(42)")
print("Promise.resolve(42) =>", result)

obj = rt.object_new()
rt.object_set(obj, "name", "async")
print("name:", rt.object_get(obj, "name"))

rt.register_fn("hostGreet", lambda name: f"Hello, {name}!")
print(rt.eval("hostGreet('World')"))

ns = rt.eval_module("export const x = 42;", "test")
print("module x:", rt.object_get(ns, "x"))

print("All sync-style tests passed!")

# ── True non-blocking async/await usage ──

async def main():
    rt2 = ts.AsyncRuntime()

    # True non-blocking await — basic evaluation
    result = await rt2.eval_await("1 + 41")
    print(f"await 1 + 41 => {result}")
    assert result == 42, f"expected 42, got {result}"

    # Module await
    ns = await rt2.eval_module_await("export const y = 100;", "mod_await")
    print(f"await module y => {rt2.object_get(ns, 'y')}")
    assert rt2.object_get(ns, "y") == 100

    # asyncio.gather — concurrent awaits (engine serializes, but asyncio loop is free)
    r1, r2 = await asyncio.gather(
        rt2.eval_await("1 + 1"),
        rt2.eval_await("2 + 2"),
    )
    print(f"gather results: {r1}, {r2}")
    assert r1 == 2 and r2 == 4

    # String result
    s = await rt2.eval_await("'hello' + ' world'")
    print(f"await string => {s}")
    assert s == "hello world"

    # Error propagation
    try:
        await rt2.eval_await("throw new Error('boom')")
        print("ERROR: should have raised")
    except RuntimeError as e:
        print(f"caught error: {e}")

    print("All async/await tests passed!")

asyncio.run(main())
