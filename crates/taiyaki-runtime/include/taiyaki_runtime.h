#ifndef TAIYAKI_RUNTIME_H
#define TAIYAKI_RUNTIME_H

#include <stdint.h>
#include <stddef.h>

/* Opaque handle to the full runtime (tokio + async engine + all builtins) */
struct TaiyakiFullRuntime;

/* C callback type for AOT-compiled f64 functions */
typedef double (*TaiyakiAotFnF64)(const double *args, uintptr_t argc, void *user_data);

/* Typed argument for generic host functions */
enum TaiyakiArgType {
    TAIYAKI_ARG_NUMBER = 0,
    TAIYAKI_ARG_STRING = 1,
    TAIYAKI_ARG_BOOL   = 2,
    TAIYAKI_ARG_NULL   = 3,
};

struct TaiyakiArg {
    enum TaiyakiArgType type;
    double number;
    const char *string;
    uintptr_t string_len;
};

/* C callback type for generic host functions (supports strings) */
typedef double (*TaiyakiHostFnGeneric)(
    const struct TaiyakiArg *args, uintptr_t argc, void *user_data);

/* Create a full runtime with all builtins (HTTP server, Web APIs, Node polyfills).
   Returns NULL on failure. */
struct TaiyakiFullRuntime *taiyaki_full_runtime_new(int argc, const char *const *argv);

/* Register an AOT-compiled f64 function as a JS global. Returns 0 on success. */
int32_t taiyaki_full_runtime_register_fn_f64(
    struct TaiyakiFullRuntime *rt,
    const char *name, uintptr_t name_len,
    TaiyakiAotFnF64 callback,
    uintptr_t declared_argc, void *user_data);

/* Register a generic host function (supports string/number/bool args). Returns 0 on success. */
int32_t taiyaki_full_runtime_register_fn(
    struct TaiyakiFullRuntime *rt,
    const char *name, uintptr_t name_len,
    TaiyakiHostFnGeneric callback,
    uintptr_t declared_argc, void *user_data);

/* Evaluate JS code. Returns 0 on success, -1 on error. */
int32_t taiyaki_full_runtime_eval(
    struct TaiyakiFullRuntime *rt,
    const char *code, uintptr_t code_len);

/* Evaluate JS code as an ES module and run the event loop (blocking).
   Returns 0 on success, -1 on error. */
int32_t taiyaki_full_runtime_eval_module_and_run(
    struct TaiyakiFullRuntime *rt,
    const char *code, uintptr_t code_len,
    const char *name, uintptr_t name_len);

/* Free the runtime. NULL-safe. */
void taiyaki_full_runtime_free(struct TaiyakiFullRuntime *rt);

#endif /* TAIYAKI_RUNTIME_H */
