#include <stdio.h>
#include <string.h>
#include "../../include/libts.h"

int main(void) {
    /* ランタイム作成 */
    struct libts_runtime *rt = libts_runtime_new();
    if (!rt) {
        fprintf(stderr, "Error: %s\n", libts_get_last_error());
        return 1;
    }

    /* JavaScript 評価 */
    const char *js_code = "1 + 2";
    struct libts_value *val = libts_eval(rt, js_code, strlen(js_code));
    if (!val) {
        fprintf(stderr, "Eval error: %s\n", libts_get_last_error());
        libts_runtime_free(rt);
        return 1;
    }

    printf("JS: 1 + 2 = %.0f\n", libts_value_as_number(val));
    libts_value_free(val);

    /* TypeScript 評価 */
    const char *ts_code = "const x: number = 42; x";
    val = libts_eval_ts(rt, ts_code, strlen(ts_code));
    if (!val) {
        fprintf(stderr, "TS eval error: %s\n", libts_get_last_error());
        libts_runtime_free(rt);
        return 1;
    }

    printf("TS: const x: number = 42; x => %.0f\n", libts_value_as_number(val));
    libts_value_free(val);

    /* 文字列評価 */
    const char *str_code = "'hello' + ' from libts'";
    val = libts_eval(rt, str_code, strlen(str_code));
    if (val) {
        uintptr_t len = 0;
        const char *s = libts_value_as_string(val, &len);
        if (s) {
            printf("JS: 'hello' + ' from libts' => %s (len=%zu)\n", s, len);
        }
        libts_value_free(val);
    }

    libts_runtime_free(rt);
    return 0;
}
