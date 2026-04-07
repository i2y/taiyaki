/**
 * Tsuchi Clay TUI Wrapper: Flat C API for Clay + termbox2 rendering.
 *
 * Provides a simple function-call interface to Clay's layout engine
 * with termbox2 as the terminal renderer. Analogous to tsuchi_clay_wrapper.c
 * but for TUI output instead of GUI (raylib).
 */

#define CLAY_IMPLEMENTATION
#include "clay.h"

#define TB_OPT_ATTR_W 32
#define TB_IMPL
#include "../termbox2/termbox2.h"

#include "clay_renderer_termbox2.c"

#include <stdlib.h>
#include <string.h>

/* ---- State ---- */
static Clay_Arena clay_tui_arena;
static Clay_RenderCommandArray clay_tui_last_commands;
static int clay_tui_initialized = 0;

/* Pool for text configs — Clay stores pointers, so they must persist per frame */
#define MAX_TEXT_CONFIGS 1024
static Clay_TextElementConfig _tui_text_configs[MAX_TEXT_CONFIGS];
static int _tui_text_config_count = 0;

/* Per-frame string pool */
#define STRING_POOL_SIZE (64 * 1024)
static char _tui_string_pool[STRING_POOL_SIZE];
static int _tui_string_pool_pos = 0;

/* Event storage */
static struct tb_event _tui_last_event;
static int _tui_last_event_valid = 0;

/* ---- Helpers ---- */

static const char *_tui_pool_string(const char *s) {
    int len = (int)strlen(s);
    if (_tui_string_pool_pos + len + 1 > STRING_POOL_SIZE) {
        return s;  /* pool full — fallback */
    }
    char *copy = _tui_string_pool + _tui_string_pool_pos;
    memcpy(copy, s, len);
    copy[len] = '\0';
    _tui_string_pool_pos += len + 1;
    return copy;
}

static Clay_SizingAxis _tui_make_sizing(double v) {
    if (v == 0)  return (Clay_SizingAxis){ .type = CLAY__SIZING_TYPE_FIT };
    if (v == -1) return (Clay_SizingAxis){ .type = CLAY__SIZING_TYPE_GROW };
    if (v <= -2) return (Clay_SizingAxis){ .size.percent = (float)(-v / 100.0), .type = CLAY__SIZING_TYPE_PERCENT };
    return (Clay_SizingAxis){ .size.minMax = {(float)v, (float)v}, .type = CLAY__SIZING_TYPE_FIXED };
}

/* ---- Lifecycle ---- */

void tsuchi_clay_tui_init(int color_mode) {
    if (clay_tui_initialized) return;

    tb_init();
    /* Set color mode: 0=normal, 1=256, 2=truecolor */
    if (color_mode == 1) {
        tb_set_output_mode(TB_OUTPUT_256);
    } else if (color_mode >= 2) {
        tb_set_output_mode(TB_OUTPUT_TRUECOLOR);
    }
    tb_set_input_mode(TB_INPUT_ESC | TB_INPUT_MOUSE);

    int tw = tb_width();
    int th = tb_height();

    uint32_t mem_size = Clay_MinMemorySize();
    clay_tui_arena = Clay_CreateArenaWithCapacityAndMemory(mem_size, malloc(mem_size));
    Clay_Initialize(clay_tui_arena, (Clay_Dimensions){(float)tw, (float)th},
                    (Clay_ErrorHandler){0});
    Clay_SetMeasureTextFunction(Termbox_MeasureText, NULL);

    clay_tui_initialized = 1;
}

void tsuchi_clay_tui_destroy(void) {
    if (clay_tui_arena.memory) {
        free(clay_tui_arena.memory);
        clay_tui_arena.memory = NULL;
    }
    clay_tui_initialized = 0;
    tb_shutdown();
}

void tsuchi_clay_tui_set_dimensions(int width, int height) {
    Clay_SetLayoutDimensions((Clay_Dimensions){(float)width, (float)height});
}

void tsuchi_clay_tui_begin_layout(void) {
    _tui_text_config_count = 0;
    _tui_string_pool_pos = 0;
    Clay_BeginLayout();
}

void tsuchi_clay_tui_end_layout(void) {
    clay_tui_last_commands = Clay_EndLayout();
}

void tsuchi_clay_tui_render(void) {
    tb_clear();
    Clay_Termbox_Render(clay_tui_last_commands);
    tb_present();
}

/* ---- Element API ---- */

void tsuchi_clay_tui_open(const char *id,
                           double sizingW, double sizingH,
                           int padTop, int padRight, int padBottom, int padLeft,
                           int childGap, int direction,
                           int bgR, int bgG, int bgB, int bgA,
                           double cornerRadius) {
    if (id && id[0]) {
        const char *pooled = _tui_pool_string(id);
        Clay_String s = { .length = (int32_t)strlen(pooled), .chars = pooled };
        Clay_ElementId eid = Clay__HashString(s, 0);
        Clay__OpenElementWithId(eid);
    } else {
        Clay__OpenElement();
    }

    Clay_ElementDeclaration config = {
        .layout = {
            .sizing = { .width = _tui_make_sizing(sizingW), .height = _tui_make_sizing(sizingH) },
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

void tsuchi_clay_tui_close_element(void) {
    Clay__CloseElement();
}

void tsuchi_clay_tui_text(const char *text, int fontSize, int fontId,
                           int r, int g, int b, int a) {
    if (!text) return;
    if (_tui_text_config_count >= MAX_TEXT_CONFIGS) return;
    const char *pooled = _tui_pool_string(text);
    Clay_String str = { .length = (int32_t)strlen(pooled), .chars = pooled };
    Clay_TextElementConfig *cfg = &_tui_text_configs[_tui_text_config_count++];
    cfg->fontSize = (uint16_t)fontSize;
    cfg->fontId = (uint16_t)fontId;
    cfg->textColor = (Clay_Color){ (float)r, (float)g, (float)b, (float)a };
    Clay__OpenTextElement(str, cfg);
}

/* ---- Pointer / Hover ---- */

void tsuchi_clay_tui_set_pointer(double x, double y, int down) {
    Clay_SetPointerState((Clay_Vector2){(float)x, (float)y}, down != 0);
}

int tsuchi_clay_tui_pointer_over(const char *id) {
    if (!id) return 0;
    const char *pooled = _tui_pool_string(id);
    Clay_String s = { .length = (int32_t)strlen(pooled), .chars = pooled };
    Clay_ElementId eid = Clay__HashString(s, 0);
    return Clay_PointerOver(eid) ? 1 : 0;
}

/* ---- Events ---- */

int tsuchi_clay_tui_peek_event(int timeout_ms) {
    int result = tb_peek_event(&_tui_last_event, timeout_ms);
    _tui_last_event_valid = (result == TB_OK) ? 1 : 0;
    return _tui_last_event_valid ? (int)_tui_last_event.type : 0;
}

int tsuchi_clay_tui_poll_event(void) {
    int result = tb_poll_event(&_tui_last_event);
    _tui_last_event_valid = (result == TB_OK) ? 1 : 0;
    return _tui_last_event_valid ? (int)_tui_last_event.type : 0;
}

int tsuchi_clay_tui_event_type(void) {
    return _tui_last_event_valid ? (int)_tui_last_event.type : 0;
}

int tsuchi_clay_tui_event_key(void) {
    return _tui_last_event_valid ? (int)_tui_last_event.key : 0;
}

int tsuchi_clay_tui_event_ch(void) {
    return _tui_last_event_valid ? (int)_tui_last_event.ch : 0;
}

int tsuchi_clay_tui_event_w(void) {
    return _tui_last_event_valid ? (int)_tui_last_event.w : 0;
}

int tsuchi_clay_tui_event_h(void) {
    return _tui_last_event_valid ? (int)_tui_last_event.h : 0;
}

/* ---- Terminal Info ---- */

int tsuchi_clay_tui_term_width(void) {
    return tb_width();
}

int tsuchi_clay_tui_term_height(void) {
    return tb_height();
}

/* ---- Key Constants ---- */

int tsuchi_clay_tui_key_esc(void)         { return TB_KEY_ESC; }
int tsuchi_clay_tui_key_enter(void)       { return TB_KEY_ENTER; }
int tsuchi_clay_tui_key_tab(void)         { return TB_KEY_TAB; }
int tsuchi_clay_tui_key_backspace(void)   { return TB_KEY_BACKSPACE2; }
int tsuchi_clay_tui_key_arrow_up(void)    { return TB_KEY_ARROW_UP; }
int tsuchi_clay_tui_key_arrow_down(void)  { return TB_KEY_ARROW_DOWN; }
int tsuchi_clay_tui_key_arrow_left(void)  { return TB_KEY_ARROW_LEFT; }
int tsuchi_clay_tui_key_arrow_right(void) { return TB_KEY_ARROW_RIGHT; }
int tsuchi_clay_tui_key_space(void)       { return TB_KEY_SPACE; }
int tsuchi_clay_tui_key_delete(void)      { return TB_KEY_DELETE; }
int tsuchi_clay_tui_key_home(void)        { return TB_KEY_HOME; }
int tsuchi_clay_tui_key_end(void)         { return TB_KEY_END; }
int tsuchi_clay_tui_key_pgup(void)        { return TB_KEY_PGUP; }
int tsuchi_clay_tui_key_pgdn(void)        { return TB_KEY_PGDN; }
int tsuchi_clay_tui_key_f1(void)          { return TB_KEY_F1; }
int tsuchi_clay_tui_key_f2(void)          { return TB_KEY_F2; }
int tsuchi_clay_tui_key_f3(void)          { return TB_KEY_F3; }
int tsuchi_clay_tui_key_f4(void)          { return TB_KEY_F4; }
int tsuchi_clay_tui_key_f5(void)          { return TB_KEY_F5; }
int tsuchi_clay_tui_key_f6(void)          { return TB_KEY_F6; }
int tsuchi_clay_tui_key_f7(void)          { return TB_KEY_F7; }
int tsuchi_clay_tui_key_f8(void)          { return TB_KEY_F8; }
int tsuchi_clay_tui_key_f9(void)          { return TB_KEY_F9; }
int tsuchi_clay_tui_key_f10(void)         { return TB_KEY_F10; }
int tsuchi_clay_tui_key_f11(void)         { return TB_KEY_F11; }
int tsuchi_clay_tui_key_f12(void)         { return TB_KEY_F12; }

/* ---- Event Modifier (Phase 4) ---- */

int tsuchi_clay_tui_event_mod(void) {
    return _tui_last_event_valid ? (int)_tui_last_event.mod : 0;
}

/* ---- Border (Phase 4) ---- */

/* Note: Clay border must be applied right after open, before children.
   This uses Clay__AttachElementConfig to add border config to current open element. */
void tsuchi_clay_tui_border(int r, int g, int b, int a,
                            int top, int right, int bottom, int left,
                            double cornerRadius) {
    /* Border is part of the element config — we configure the currently open element.
       Clay uses ConfigureOpenElement, so we re-open with border config.
       For simplicity, we store border info as a rectangle decoration in the render. */
    (void)r; (void)g; (void)b; (void)a;
    (void)top; (void)right; (void)bottom; (void)left;
    (void)cornerRadius;
    /* TODO: Clay border support requires Clay_BorderElementConfig attachment.
       Currently a no-op placeholder until Clay border API is integrated. */
}

/* ---- Alignment (Phase 4) ---- */

void tsuchi_clay_tui_align(int ax, int ay) {
    /* Alignment hints for current open element.
       ax: 0=LEFT, 1=CENTER, 2=RIGHT
       ay: 0=TOP, 1=CENTER, 2=BOTTOM */
    (void)ax; (void)ay;
    /* TODO: Clay alignment requires childAlignment config.
       Currently a no-op placeholder. */
}

/* ---- Scroll (Phase 4) ---- */

void tsuchi_clay_tui_scroll(int h, int v) {
    /* Enable scroll axes on current element. h=horizontal, v=vertical */
    (void)h; (void)v;
    /* TODO: Clay scroll config requires CLAY_SCROLL element config.
       Currently a no-op placeholder. */
}

void tsuchi_clay_tui_update_scroll(double dx, double dy, double dt) {
    Clay_UpdateScrollContainers(1, (Clay_Vector2){(float)dx, (float)dy}, (float)dt);
}

/* ---- Open Indexed (Phase 4) ---- */

void tsuchi_clay_tui_openI(const char *id, int index,
                            double sizingW, double sizingH,
                            int padTop, int padRight, int padBottom, int padLeft,
                            int childGap, int direction,
                            int bgR, int bgG, int bgB, int bgA,
                            double cornerRadius) {
    if (id && id[0]) {
        const char *pooled = _tui_pool_string(id);
        Clay_String s = { .length = (int32_t)strlen(pooled), .chars = pooled };
        Clay_ElementId eid = Clay__HashString(s, (uint32_t)index);
        Clay__OpenElementWithId(eid);
    } else {
        Clay__OpenElement();
    }

    Clay_ElementDeclaration config = {
        .layout = {
            .sizing = { .width = _tui_make_sizing(sizingW), .height = _tui_make_sizing(sizingH) },
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

/* ---- Text Buffer (Phase 4) ---- */

#define TEXTBUF_MAX 4096
static char _tui_textbuf[TEXTBUF_MAX];
static int _tui_textbuf_len = 0;
static int _tui_textbuf_cursor = 0;

void tsuchi_clay_tui_textbuf_clear(void) {
    _tui_textbuf_len = 0;
    _tui_textbuf_cursor = 0;
    _tui_textbuf[0] = '\0';
}

void tsuchi_clay_tui_textbuf_putchar(int ch) {
    if (_tui_textbuf_len >= TEXTBUF_MAX - 1) return;
    /* Insert at cursor position */
    if (_tui_textbuf_cursor < _tui_textbuf_len) {
        memmove(&_tui_textbuf[_tui_textbuf_cursor + 1],
                &_tui_textbuf[_tui_textbuf_cursor],
                _tui_textbuf_len - _tui_textbuf_cursor);
    }
    _tui_textbuf[_tui_textbuf_cursor] = (char)ch;
    _tui_textbuf_len++;
    _tui_textbuf_cursor++;
    _tui_textbuf[_tui_textbuf_len] = '\0';
}

void tsuchi_clay_tui_textbuf_backspace(void) {
    if (_tui_textbuf_cursor <= 0) return;
    _tui_textbuf_cursor--;
    memmove(&_tui_textbuf[_tui_textbuf_cursor],
            &_tui_textbuf[_tui_textbuf_cursor + 1],
            _tui_textbuf_len - _tui_textbuf_cursor);
    _tui_textbuf_len--;
}

void tsuchi_clay_tui_textbuf_delete(void) {
    if (_tui_textbuf_cursor >= _tui_textbuf_len) return;
    memmove(&_tui_textbuf[_tui_textbuf_cursor],
            &_tui_textbuf[_tui_textbuf_cursor + 1],
            _tui_textbuf_len - _tui_textbuf_cursor);
    _tui_textbuf_len--;
}

void tsuchi_clay_tui_textbuf_cursor_left(void) {
    if (_tui_textbuf_cursor > 0) _tui_textbuf_cursor--;
}

void tsuchi_clay_tui_textbuf_cursor_right(void) {
    if (_tui_textbuf_cursor < _tui_textbuf_len) _tui_textbuf_cursor++;
}

void tsuchi_clay_tui_textbuf_home(void) {
    _tui_textbuf_cursor = 0;
}

void tsuchi_clay_tui_textbuf_end(void) {
    _tui_textbuf_cursor = _tui_textbuf_len;
}

int tsuchi_clay_tui_textbuf_len(void) {
    return _tui_textbuf_len;
}

int tsuchi_clay_tui_textbuf_cursor(void) {
    return _tui_textbuf_cursor;
}

void tsuchi_clay_tui_textbuf_render(int fontSize, int fontId,
                                     int r, int g, int b, int a) {
    /* Render the text buffer content as a Clay text element */
    if (_tui_text_config_count >= MAX_TEXT_CONFIGS) return;
    const char *pooled = _tui_pool_string(_tui_textbuf);
    Clay_String str = { .length = (int32_t)_tui_textbuf_len, .chars = pooled };
    Clay_TextElementConfig *cfg = &_tui_text_configs[_tui_text_config_count++];
    cfg->fontSize = (uint16_t)fontSize;
    cfg->fontId = (uint16_t)fontId;
    cfg->textColor = (Clay_Color){ (float)r, (float)g, (float)b, (float)a };
    Clay__OpenTextElement(str, cfg);
}

/* ---- Phase B Extensions ---- */

/* textbufCopy: return a pointer to the text buffer content (NUL-terminated) */
const char *tsuchi_clay_tui_textbuf_copy(void) {
    _tui_textbuf[_tui_textbuf_len] = '\0';
    return _tui_textbuf;
}

/* textbufRenderRange: render a sub-range of the text buffer */
void tsuchi_clay_tui_textbuf_render_range(int start, int len,
                                           int fontSize, int fontId,
                                           int r, int g, int b, int a) {
    if (_tui_text_config_count >= MAX_TEXT_CONFIGS) return;
    if (start < 0) start = 0;
    if (start >= _tui_textbuf_len) return;
    if (start + len > _tui_textbuf_len) len = _tui_textbuf_len - start;
    if (len <= 0) return;
    /* Pool a sub-string */
    if (_tui_string_pool_pos + len + 1 > STRING_POOL_SIZE) return;
    char *copy = _tui_string_pool + _tui_string_pool_pos;
    memcpy(copy, _tui_textbuf + start, len);
    copy[len] = '\0';
    _tui_string_pool_pos += len + 1;

    Clay_String str = { .length = (int32_t)len, .chars = copy };
    Clay_TextElementConfig *cfg = &_tui_text_configs[_tui_text_config_count++];
    cfg->fontSize = (uint16_t)fontSize;
    cfg->fontId = (uint16_t)fontId;
    cfg->textColor = (Clay_Color){ (float)r, (float)g, (float)b, (float)a };
    Clay__OpenTextElement(str, cfg);
}

/* textChar: render a single character as a Clay text element */
void tsuchi_clay_tui_text_char(int ch, int fontSize, int fontId,
                                int r, int g, int b, int a) {
    if (_tui_text_config_count >= MAX_TEXT_CONFIGS) return;
    if (_tui_string_pool_pos + 2 > STRING_POOL_SIZE) return;
    char *s = _tui_string_pool + _tui_string_pool_pos;
    s[0] = (char)ch;
    s[1] = '\0';
    _tui_string_pool_pos += 2;

    Clay_String str = { .length = 1, .chars = s };
    Clay_TextElementConfig *cfg = &_tui_text_configs[_tui_text_config_count++];
    cfg->fontSize = (uint16_t)fontSize;
    cfg->fontId = (uint16_t)fontId;
    cfg->textColor = (Clay_Color){ (float)r, (float)g, (float)b, (float)a };
    Clay__OpenTextElement(str, cfg);
}

/* pointerOverI: indexed hover detection */
int tsuchi_clay_tui_pointer_over_i(const char *id, int index) {
    if (!id || !id[0]) return 0;
    const char *pooled = _tui_pool_string(id);
    Clay_String s = { .length = (int32_t)strlen(pooled), .chars = pooled };
    Clay_ElementId eid = Clay__HashString(s, (uint32_t)index);
    return Clay_PointerOver(eid) ? 1 : 0;
}

/* eventMouseX/Y: mouse coordinates from last event */
int tsuchi_clay_tui_event_mouse_x(void) {
    return _tui_last_event_valid ? _tui_last_event.x : 0;
}

int tsuchi_clay_tui_event_mouse_y(void) {
    return _tui_last_event_valid ? _tui_last_event.y : 0;
}

/* rgb: pack terminal RGB into a single int for truecolor */
int tsuchi_clay_tui_rgb(int r, int g, int b) {
    /* termbox2 truecolor: 0x01RRGGBB format */
    return 0x01000000 | ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF);
}

/* bgEx: set background color with attribute on the current element */
void tsuchi_clay_tui_bg_ex(int r, int g, int b, int a, int attr) {
    (void)r; (void)g; (void)b; (void)a; (void)attr;
    /* Background + attribute support depends on renderer extension */
}

/* textEx: text with foreground, background, and attribute */
void tsuchi_clay_tui_text_ex(const char *text, int fontSize, int fontId,
                              int r, int g, int b, int a,
                              int bgR, int bgG, int bgB, int bgA,
                              int attr) {
    if (_tui_text_config_count >= MAX_TEXT_CONFIGS) return;
    const char *pooled = _tui_pool_string(text);
    Clay_String str = { .length = (int32_t)strlen(pooled), .chars = pooled };
    Clay_TextElementConfig *cfg = &_tui_text_configs[_tui_text_config_count++];
    cfg->fontSize = (uint16_t)fontSize;
    cfg->fontId = (uint16_t)fontId;
    cfg->textColor = (Clay_Color){ (float)r, (float)g, (float)b, (float)a };
    (void)bgR; (void)bgG; (void)bgB; (void)bgA; (void)attr;
    Clay__OpenTextElement(str, cfg);
}

/* floating: configure floating element positioning */
void tsuchi_clay_tui_floating(double offsetX, double offsetY,
                               int zIndex, int attachElem, int attachParent) {
    Clay_FloatingElementConfig fconfig = {0};
    fconfig.offset = (Clay_Vector2){ (float)offsetX, (float)offsetY };
    fconfig.zIndex = (int16_t)zIndex;
    fconfig.attachTo = (Clay_FloatingAttachToElement)attachElem;
    fconfig.parentId = (uint32_t)attachParent;
    Clay__AttachElementConfig(
        (Clay_ElementConfigUnion){ .floatingElementConfig = Clay__StoreFloatingElementConfig(fconfig) },
        CLAY__ELEMENT_CONFIG_TYPE_FLOATING
    );
}
