/**
 * Tsuchi Clay Wrapper: Flat C API for Clay + Raylib rendering.
 *
 * Provides a simple function-call interface to Clay's layout engine,
 * usable from Tsuchi's LLVM-compiled code and QuickJS fallback.
 */

#define CLAY_IMPLEMENTATION
#include "clay.h"
#include "clay_renderer_raylib.c"

#include <stdlib.h>
#include <string.h>

/* ---- State ---- */
static Clay_Arena clay_arena;
static Font clay_fonts[16];
static int clay_font_count = 0;
static Clay_RenderCommandArray clay_last_commands;
static int clay_initialized = 0;

/* Pool for text configs — Clay stores pointers, so they must persist per frame */
#define MAX_TEXT_CONFIGS 1024
static Clay_TextElementConfig _text_configs[MAX_TEXT_CONFIGS];
static int _text_config_count = 0;

/* ---- Lifecycle ---- */

/* Reference custom font from raylib runtime (if loaded) */
extern Font _tsuchi_custom_font;
extern int _tsuchi_has_custom_font;

void tsuchi_clay_init(int width, int height) {
    if (clay_initialized) return;
    uint32_t mem_size = Clay_MinMemorySize();
    clay_arena = Clay_CreateArenaWithCapacityAndMemory(mem_size, malloc(mem_size));
    Clay_Initialize(clay_arena, (Clay_Dimensions){(float)width, (float)height},
                    (Clay_ErrorHandler){0});
    /* Use custom font if loaded, otherwise default */
    if (_tsuchi_has_custom_font) {
        clay_fonts[0] = _tsuchi_custom_font;
    } else {
        clay_fonts[0] = GetFontDefault();
    }
    clay_font_count = 1;
    Clay_SetMeasureTextFunction(Raylib_MeasureText, clay_fonts);
    clay_initialized = 1;
}

int tsuchi_clay_load_font(const char *path, int size) {
    if (clay_font_count >= 16) return 0;
    int id;
    if (clay_font_count <= 1) {
        /* First user font replaces default at slot 0 */
        id = 0;
        clay_fonts[0] = LoadFontEx(path, size, NULL, 0);
        if (clay_font_count == 0) clay_font_count = 1;
    } else {
        id = clay_font_count;
        clay_fonts[id] = LoadFontEx(path, size, NULL, 0);
        clay_font_count++;
    }
    return id;
}

void tsuchi_clay_set_dimensions(int width, int height) {
    Clay_SetLayoutDimensions((Clay_Dimensions){(float)width, (float)height});
}

void tsuchi_clay_set_pointer(double x, double y, int down) {
    Clay_SetPointerState((Clay_Vector2){(float)x, (float)y}, down != 0);
}

void tsuchi_clay_update_scroll(double dx, double dy, double dt) {
    Clay_UpdateScrollContainers(true, (Clay_Vector2){(float)dx, (float)dy}, (float)dt);
}

void tsuchi_clay_begin_layout(void) {
    _text_config_count = 0;
    /* Sync custom font if loaded after clay init */
    if (_tsuchi_has_custom_font) {
        clay_fonts[0] = _tsuchi_custom_font;
    }
    Clay_BeginLayout();
}

void tsuchi_clay_end_layout(void) {
    clay_last_commands = Clay_EndLayout();
}

void tsuchi_clay_render(void) {
    Clay_Raylib_Render(clay_last_commands, clay_fonts);
}

/* ---- Element API ---- */

/*
 * Open a container element with common layout properties.
 * sizingW/sizingH: 0 = fit, >0 = fixed px, -1 = grow, -2..-100 = percent (negate to get %)
 * direction: 0 = left-to-right, 1 = top-to-bottom
 */
static Clay_SizingAxis _make_sizing(double v) {
    if (v == 0)  return (Clay_SizingAxis){ .type = CLAY__SIZING_TYPE_FIT };
    if (v == -1) return (Clay_SizingAxis){ .type = CLAY__SIZING_TYPE_GROW };
    if (v <= -2) return (Clay_SizingAxis){ .size.percent = (float)(-v / 100.0), .type = CLAY__SIZING_TYPE_PERCENT };
    return (Clay_SizingAxis){ .size.minMax = {(float)v, (float)v}, .type = CLAY__SIZING_TYPE_FIXED };
}

void tsuchi_clay_open(const char *id,
                       double sizingW, double sizingH,
                       int padTop, int padRight, int padBottom, int padLeft,
                       int childGap, int direction,
                       int bgR, int bgG, int bgB, int bgA,
                       double cornerRadius) {
    /* Open element with ID */
    if (id && id[0]) {
        Clay_String s = { .length = (int32_t)strlen(id), .chars = id };
        Clay_ElementId eid = Clay__HashString(s, 0);
        Clay__OpenElementWithId(eid);
    } else {
        Clay__OpenElement();
    }

    Clay_ElementDeclaration config = {
        .layout = {
            .sizing = { .width = _make_sizing(sizingW), .height = _make_sizing(sizingH) },
            .padding = { .left = (float)padLeft, .right = (float)padRight,
                         .top = (float)padTop, .bottom = (float)padBottom },
            .childGap = (uint16_t)childGap,
            .layoutDirection = direction ? CLAY_TOP_TO_BOTTOM : CLAY_LEFT_TO_RIGHT,
        },
        .backgroundColor = { (float)bgR, (float)bgG, (float)bgB, (float)bgA },
        .cornerRadius = { (float)cornerRadius, (float)cornerRadius,
                          (float)cornerRadius, (float)cornerRadius },
    };

    Clay__ConfigureOpenElement(config);
}

/* Open element with alignment support (ax: 0=LEFT,1=RIGHT,2=CENTER, ay: 0=TOP,1=BOTTOM,2=CENTER) */
void tsuchi_clay_open_aligned(const char *id,
                              double sizingW, double sizingH,
                              int padTop, int padRight, int padBottom, int padLeft,
                              int childGap, int direction,
                              int bgR, int bgG, int bgB, int bgA,
                              double cornerRadius, int alignX, int alignY) {
    if (id && id[0]) {
        Clay_String s = { .length = (int32_t)strlen(id), .chars = id };
        Clay_ElementId eid = Clay__HashString(s, 0);
        Clay__OpenElementWithId(eid);
    } else {
        Clay__OpenElement();
    }
    Clay_ElementDeclaration config = {
        .layout = {
            .sizing = { .width = _make_sizing(sizingW), .height = _make_sizing(sizingH) },
            .padding = { .left = (float)padLeft, .right = (float)padRight,
                         .top = (float)padTop, .bottom = (float)padBottom },
            .childGap = (uint16_t)childGap,
            .layoutDirection = direction ? CLAY_TOP_TO_BOTTOM : CLAY_LEFT_TO_RIGHT,
            .childAlignment = { .x = (Clay_LayoutAlignmentX)alignX,
                                .y = (Clay_LayoutAlignmentY)alignY },
        },
        .backgroundColor = { (float)bgR, (float)bgG, (float)bgB, (float)bgA },
        .cornerRadius = { (float)cornerRadius, (float)cornerRadius,
                          (float)cornerRadius, (float)cornerRadius },
    };
    Clay__ConfigureOpenElement(config);
}

void tsuchi_clay_close(void) {
    Clay__CloseElement();
}

/*
 * Add a text element.
 * fontId: 0 = default font
 */
void tsuchi_clay_text(const char *text, int fontSize, int fontId,
                       int r, int g, int b, int a) {
    if (!text) return;
    if (_text_config_count >= MAX_TEXT_CONFIGS) return;
    Clay_String str = { .length = (int32_t)strlen(text), .chars = text };
    Clay_TextElementConfig *cfg = &_text_configs[_text_config_count++];
    cfg->fontSize = (uint16_t)fontSize;
    cfg->fontId = (uint16_t)fontId;
    cfg->textColor = (Clay_Color){ (float)r, (float)g, (float)b, (float)a };
    Clay__OpenTextElement(str, cfg);
}

/* ---- Scroll ---- */

void tsuchi_clay_scroll(int horizontal, int vertical) {
    Clay_ClipElementConfig clipConfig = {
        .horizontal = horizontal ? true : false,
        .vertical = vertical ? true : false,
    };
    Clay__AttachElementConfig(
        (Clay_ElementConfigUnion){ .clipElementConfig = Clay__StoreClipElementConfig(clipConfig) },
        CLAY__ELEMENT_CONFIG_TYPE_CLIP
    );
}

/* ---- Floating ---- */

void tsuchi_clay_floating(double offsetX, double offsetY, int zIndex) {
    Clay_FloatingElementConfig floatConfig = {
        .offset = { .x = (float)offsetX, .y = (float)offsetY },
        .zIndex = (int16_t)zIndex,
        .parentId = 0,
    };
    Clay__AttachElementConfig(
        (Clay_ElementConfigUnion){ .floatingElementConfig = Clay__StoreFloatingElementConfig(floatConfig) },
        CLAY__ELEMENT_CONFIG_TYPE_FLOATING
    );
}

/* ---- Border ---- */

void tsuchi_clay_border(int r, int g, int b, int a,
                        int top, int right, int bottom, int left, int radius) {
    Clay_BorderElementConfig borderConfig = {
        .color = (Clay_Color){ (float)r, (float)g, (float)b, (float)a },
        .width = {
            .top = (float)top,
            .right = (float)right,
            .bottom = (float)bottom,
            .left = (float)left,
        },
    };
    Clay__AttachElementConfig(
        (Clay_ElementConfigUnion){ .borderElementConfig = &borderConfig },
        CLAY__ELEMENT_CONFIG_TYPE_BORDER
    );
}

/* ---- Measure text (raylib) ---- */

void tsuchi_clay_set_measure_text_raylib(void) {
    Clay_SetMeasureTextFunction(Raylib_MeasureText, clay_fonts);
}

/* ---- CJK font loading ---- */

int tsuchi_clay_load_font_cjk(const char *path, int size) {
    if (clay_font_count >= 16) return 0;
    int id = clay_font_count;
    if (path && path[0]) {
        clay_fonts[id] = LoadFontEx(path, size, NULL, 0);
    } else {
        clay_fonts[id] = GetFontDefault();
    }
    clay_font_count++;
    return id;
}

/* ---- Custom element ---- */

void tsuchi_clay_set_custom(int customId) {
    Clay_CustomElementConfig customConfig = { .customData = (void*)(intptr_t)customId };
    Clay__AttachElementConfig(
        (Clay_ElementConfigUnion){ .customElementConfig = &customConfig },
        CLAY__ELEMENT_CONFIG_TYPE_CUSTOM
    );
}

/* ---- Destroy ---- */

void tsuchi_clay_destroy(void) {
    /* No-op for now; Clay doesn't have a cleanup API */
}

/* ---- Raylib render passthrough ---- */

void tsuchi_clay_render_raylib(void) {
    Clay_Raylib_Render(clay_last_commands, clay_fonts);
}

/* ---- Resize callback (live redraw on macOS) ---- */

/* GLFW forward declarations (linked via raylib static lib) */
typedef struct GLFWwindow GLFWwindow;
typedef void (*GLFWwindowrefreshfun)(GLFWwindow*);
typedef void (*GLFWframebuffersizefun)(GLFWwindow*, int, int);
extern GLFWwindow* glfwGetCurrentContext(void);
extern GLFWwindowrefreshfun glfwSetWindowRefreshCallback(GLFWwindow*, GLFWwindowrefreshfun);
extern GLFWframebuffersizefun glfwSetFramebufferSizeCallback(GLFWwindow*, GLFWframebuffersizefun);
extern void glfwGetFramebufferSize(GLFWwindow*, int*, int*);
extern void glfwSwapBuffers(GLFWwindow*);

/* rlgl forward declarations (part of raylib) */
extern void rlViewport(int x, int y, int width, int height);
extern void rlClearColor(unsigned char r, unsigned char g, unsigned char b, unsigned char a);
extern void rlClearScreenBuffers(void);
extern void rlDrawRenderBatchActive(void);

static int _tsuchi_bg_r = 18, _tsuchi_bg_g = 18, _tsuchi_bg_b = 28;

/* App-provided full-frame callback (called during live resize) */
typedef void (*tsuchi_frame_fn)(void);
static tsuchi_frame_fn _tsuchi_resize_frame_fn = NULL;

void tsuchi_clay_set_resize_frame(tsuchi_frame_fn fn) {
    _tsuchi_resize_frame_fn = fn;
}

static void _tsuchi_framebuffer_size_cb(GLFWwindow *window, int w, int h) {
    (void)window;
    rlViewport(0, 0, w, h);
    Clay_SetLayoutDimensions((Clay_Dimensions){(float)w, (float)h});
}

static void _tsuchi_window_refresh_cb(GLFWwindow *window) {
    int w, h;
    glfwGetFramebufferSize(window, &w, &h);
    rlViewport(0, 0, w, h);
    Clay_SetLayoutDimensions((Clay_Dimensions){(float)w, (float)h});

    if (_tsuchi_resize_frame_fn) {
        /* Full relayout: call back into app to run draw + render */
        _tsuchi_resize_frame_fn();
    } else {
        /* Fallback: re-render last frame's commands */
        rlClearColor((unsigned char)_tsuchi_bg_r,
                     (unsigned char)_tsuchi_bg_g,
                     (unsigned char)_tsuchi_bg_b, 255);
        rlClearScreenBuffers();
        if (clay_last_commands.length > 0) {
            Clay_Raylib_Render(clay_last_commands, clay_fonts);
        }
        rlDrawRenderBatchActive();
        glfwSwapBuffers(window);
    }
}

void tsuchi_clay_register_resize_callback(void) {
    GLFWwindow* window = glfwGetCurrentContext();
    if (window) {
        glfwSetFramebufferSizeCallback(window, _tsuchi_framebuffer_size_cb);
        glfwSetWindowRefreshCallback(window, _tsuchi_window_refresh_cb);
    }
}

/* ---- Background color ---- */

void tsuchi_clay_set_bg_color(int r, int g, int b) {
    _tsuchi_bg_r = r;
    _tsuchi_bg_g = g;
    _tsuchi_bg_b = b;
}

/* ---- Hover detection ---- */

int tsuchi_clay_pointer_over(const char *id) {
    if (!id) return 0;
    Clay_String s = { .length = (int32_t)strlen(id), .chars = id };
    Clay_ElementId eid = Clay__HashString(s, 0);
    return Clay_PointerOver(eid) ? 1 : 0;
}
