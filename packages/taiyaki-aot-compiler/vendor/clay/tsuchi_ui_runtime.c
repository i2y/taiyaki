/*
 * Tsuchi UI Runtime — C helpers for interactive UI widgets
 *
 * Provides focus management, click detection, text buffer management,
 * and widget state tracking for the IMGUI-style UI widget system.
 *
 * Works with both Clay (raylib) and ClayTUI (termbox2) backends.
 * Widget rendering is done via Clay's layout engine; this file
 * handles the interactive state layer on top.
 */

#include <string.h>
#include <stdio.h>

/* Forward declarations — defined in tsuchi_clay_wrapper.c (included before this file) */
int tsuchi_clay_pointer_over(const char *id);
void tsuchi_clay_open(const char *id,
                      double sizingW, double sizingH,
                      int padTop, int padRight, int padBottom, int padLeft,
                      int childGap, int direction,
                      int bgR, int bgG, int bgB, int bgA,
                      double cornerRadius);
void tsuchi_clay_close(void);
void tsuchi_clay_text(const char *text, int fontSize, int fontId,
                      int r, int g, int b, int a);
/* From tsuchi_clay_wrapper.c */
void tsuchi_clay_open_aligned(const char *id,
                              double sizingW, double sizingH,
                              int padTop, int padRight, int padBottom, int padLeft,
                              int childGap, int direction,
                              int bgR, int bgG, int bgB, int bgA,
                              double cornerRadius, int alignX, int alignY);

/* raylib functions — declared via raylib.h which is included by the wrapper */
/* Key codes: fallback defines if raylib.h not yet included */
#ifndef KEY_ENTER
#define KEY_ENTER       257
#define KEY_TAB         258
#define KEY_BACKSPACE   259
#define KEY_DELETE       261
#define KEY_RIGHT        262
#define KEY_LEFT         263
#define KEY_DOWN         264
#define KEY_UP           265
#define KEY_HOME         268
#define KEY_END          269
#define KEY_ESCAPE       256
#define KEY_SPACE        32
#define KEY_LEFT_SHIFT   340
#endif

/* ═══════════════════════════════════════════
 * Focus Management
 * ═══════════════════════════════════════════ */

#define UI_MAX_FOCUSABLE 256

static int ui_focus_index = 0;       /* currently focused widget */
static int ui_focus_count = 0;       /* number of focusable widgets this frame */
static int ui_auto_id_counter = 0;   /* auto-incrementing ID */
static int ui_frame_counter = 0;

/* Per-frame click/hover state keyed by string ID hash */
#define UI_MAX_WIDGETS 256
static unsigned int ui_widget_hashes[UI_MAX_WIDGETS];
static int ui_widget_clicked[UI_MAX_WIDGETS];
static int ui_widget_hovered[UI_MAX_WIDGETS];
static int ui_widget_toggled[UI_MAX_WIDGETS];
static double ui_widget_slider_val[UI_MAX_WIDGETS];
static int ui_widget_count = 0;

static unsigned int ui_hash_str(const char *s) {
    unsigned int h = 5381;
    while (*s) {
        h = ((h << 5) + h) + (unsigned char)*s;
        s++;
    }
    return h;
}

static int ui_find_or_add_widget(const char *id) {
    unsigned int h = ui_hash_str(id);
    for (int i = 0; i < ui_widget_count; i++) {
        if (ui_widget_hashes[i] == h) return i;
    }
    if (ui_widget_count >= UI_MAX_WIDGETS) return 0;
    int idx = ui_widget_count++;
    ui_widget_hashes[idx] = h;
    ui_widget_clicked[idx] = 0;
    ui_widget_hovered[idx] = 0;
    ui_widget_toggled[idx] = 0;
    ui_widget_slider_val[idx] = 0;
    return idx;
}

/* ═══════════════════════════════════════════
 * Frame Lifecycle
 * ═══════════════════════════════════════════ */

void tsuchi_ui_beginFrame(void) {
    ui_auto_id_counter = 0;
    ui_focus_count = 0;
    ui_widget_count = 0;
    ui_frame_counter++;

    /* Tab / Shift+Tab focus cycling */
    if (IsKeyPressed(KEY_TAB)) {
        if (IsKeyDown(KEY_LEFT_SHIFT)) {
            ui_focus_index--;
        } else {
            ui_focus_index++;
        }
    }
}

void tsuchi_ui_endFrame(void) {
    /* Wrap focus */
    if (ui_focus_count > 0) {
        if (ui_focus_index < 0) ui_focus_index = ui_focus_count - 1;
        if (ui_focus_index >= ui_focus_count) ui_focus_index = 0;
    }
}

/* ═══════════════════════════════════════════
 * Widget State Queries
 * ═══════════════════════════════════════════ */

int tsuchi_ui_clicked(const char *id) {
    int idx = ui_find_or_add_widget(id);
    return ui_widget_clicked[idx];
}

int tsuchi_ui_hovered(const char *id) {
    int idx = ui_find_or_add_widget(id);
    return ui_widget_hovered[idx];
}

int tsuchi_ui_toggled(const char *id) {
    int idx = ui_find_or_add_widget(id);
    return ui_widget_toggled[idx];
}

double tsuchi_ui_sliderValue(const char *id) {
    int idx = ui_find_or_add_widget(id);
    return ui_widget_slider_val[idx];
}

void tsuchi_ui_focusNext(void) { ui_focus_index++; }
void tsuchi_ui_focusPrev(void) { ui_focus_index--; }

double tsuchi_ui_keyPressed(void) {
    if (IsKeyPressed(KEY_ENTER)) return KEY_ENTER;
    if (IsKeyPressed(KEY_ESCAPE)) return KEY_ESCAPE;
    if (IsKeyPressed(KEY_TAB)) return KEY_TAB;
    if (IsKeyPressed(KEY_BACKSPACE)) return KEY_BACKSPACE;
    if (IsKeyPressed(KEY_DELETE)) return KEY_DELETE;
    if (IsKeyPressed(KEY_LEFT)) return KEY_LEFT;
    if (IsKeyPressed(KEY_RIGHT)) return KEY_RIGHT;
    if (IsKeyPressed(KEY_UP)) return KEY_UP;
    if (IsKeyPressed(KEY_DOWN)) return KEY_DOWN;
    if (IsKeyPressed(KEY_HOME)) return KEY_HOME;
    if (IsKeyPressed(KEY_END)) return KEY_END;
    if (IsKeyPressed(KEY_SPACE)) return KEY_SPACE;
    return 0;
}

double tsuchi_ui_charPressed(void) {
    return (double)GetCharPressed();
}

/* ═══════════════════════════════════════════
 * Interactive Widget Helpers
 * ═══════════════════════════════════════════ */

/* Helper: check if current focus matches, and detect interaction */
static int ui_is_focused(void) {
    return ui_focus_count == ui_focus_index;
}

static void ui_register_focusable(void) {
    ui_focus_count++;
}

/* Detect click: pointer over + mouse button pressed, OR focused + Enter */
static int ui_detect_click(const char *id) {
    int hover = tsuchi_clay_pointer_over(id);
    int click = hover && IsMouseButtonPressed(0);
    if (!click && ui_is_focused()) {
        click = IsKeyPressed(KEY_ENTER) || IsKeyPressed(KEY_SPACE);
    }
    return click;
}

/* Clamp helper */
static int ui_min(int a, int b) { return a < b ? a : b; }
static int ui_max(int a, int b) { return a > b ? a : b; }

/* ═══════════════════════════════════════════
 * Button
 * ═══════════════════════════════════════════ */

/* kind: 0=default, 1=primary, 2=success, 3=warning, 4=danger */
static void ui_kind_colors(int kind, int *r, int *g, int *b) {
    switch (kind) {
        case 1: *r = 60; *g = 100; *b = 180; break;  /* primary */
        case 2: *r = 80; *g = 200; *b = 120; break;   /* success */
        case 3: *r = 220; *g = 180; *b = 80; break;   /* warning */
        case 4: *r = 220; *g = 80; *b = 80; break;    /* danger */
        default: *r = 60; *g = 60; *b = 80; break;    /* default */
    }
}

void tsuchi_ui_buttonOpen(const char *id, double kind, double size, double flex) {
    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);
    int kr, kg, kb;
    ui_kind_colors((int)kind, &kr, &kg, &kb);

    /* Brighten on hover */
    if (hover) {
        kr = ui_min(kr + 40, 255);
        kg = ui_min(kg + 40, 255);
        kb = ui_min(kb + 40, 255);
    } else if (focused) {
        kr = ui_min(kr + 20, 255);
        kg = ui_min(kg + 20, 255);
        kb = ui_min(kb + 20, 255);
    }

    /* flex: 0=FIT, -1=GROW, >0=percentage width (1-100) + GROW height
     * _make_sizing in wrapper: 0=FIT, -1=GROW, <=-2 → PERCENT(percent=-v)
     * So flex=25 → sizingW=-25.0 → percent=25.0 */
    double sw, sh;
    int iflex = (int)flex;
    if (iflex > 0) {
        sw = -(double)iflex;  /* flex=25 → sw=-25 → PERCENT 25% */
        sh = -1.0;            /* GROW height */
    } else if (iflex < 0) {
        sw = -1.0; sh = -1.0; /* GROW both */
    } else {
        sw = 0.0; sh = 0.0;   /* FIT */
    }
    /* ax: 0=LEFT,1=RIGHT,2=CENTER  ay: 0=TOP,1=BOTTOM,2=CENTER */
    tsuchi_clay_open_aligned(id, sw, sh, 8, 12, 8, 12, 0, 0, kr, kg, kb, 255, 4.0, 2, 2);

    /* Track state */
    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = ui_detect_click(id);
}

void tsuchi_ui_buttonClose(void) {
    tsuchi_clay_close();
    ui_register_focusable();
}

/* ═══════════════════════════════════════════
 * Checkbox
 * ═══════════════════════════════════════════ */

void tsuchi_ui_checkboxOpen(const char *id, double checked, double size) {
    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);
    int bgR = 36, bgG = 36, bgB = 48;
    if (hover || focused) { bgR = 60; bgG = 60; bgB = 80; }

    tsuchi_clay_open(id, 0, 0, 2, 4, 2, 8, 4, 0, bgR, bgG, bgB, 255, 0);

    /* Emit checkbox indicator */
    if ((int)checked) {
        tsuchi_clay_text("[x] ", (int)size, 0, 80, 200, 120, 255);
    } else {
        tsuchi_clay_text("[ ] ", (int)size, 0, 80, 80, 100, 255);
    }

    ui_widget_hovered[idx] = hover;
    int click = ui_detect_click(id);
    ui_widget_clicked[idx] = click;
    ui_widget_toggled[idx] = click;
}

void tsuchi_ui_checkboxClose(void) {
    tsuchi_clay_close();
    ui_register_focusable();
}

/* ═══════════════════════════════════════════
 * Radio Button
 * ═══════════════════════════════════════════ */

void tsuchi_ui_radioOpen(const char *id, double index, double selected, double size) {
    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);
    int bgR = 36, bgG = 36, bgB = 48;
    if (hover || focused) { bgR = 60; bgG = 60; bgB = 80; }

    tsuchi_clay_open(id, 0, 0, 2, 4, 2, 8, 4, 0, bgR, bgG, bgB, 255, 0);

    if ((int)index == (int)selected) {
        tsuchi_clay_text("(*) ", (int)size, 0, 60, 100, 180, 255);
    } else {
        tsuchi_clay_text("( ) ", (int)size, 0, 80, 80, 100, 255);
    }

    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = ui_detect_click(id);
}

void tsuchi_ui_radioClose(void) {
    tsuchi_clay_close();
    ui_register_focusable();
}

/* ═══════════════════════════════════════════
 * Toggle Switch
 * ═══════════════════════════════════════════ */

void tsuchi_ui_toggleOpen(const char *id, double on, double size) {
    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);
    int bgR = 36, bgG = 36, bgB = 48;
    if (hover || focused) { bgR = 60; bgG = 60; bgB = 80; }

    tsuchi_clay_open(id, 0, 0, 2, 4, 2, 8, 6, 0, bgR, bgG, bgB, 255, 0);

    if ((int)on) {
        tsuchi_clay_text("[ON]  ", (int)size, 0, 80, 200, 120, 255);
    } else {
        tsuchi_clay_text("[OFF] ", (int)size, 0, 220, 80, 80, 255);
    }

    ui_widget_hovered[idx] = hover;
    int click = ui_detect_click(id);
    ui_widget_clicked[idx] = click;
    ui_widget_toggled[idx] = click;
}

void tsuchi_ui_toggleClose(void) {
    tsuchi_clay_close();
    ui_register_focusable();
}

/* ═══════════════════════════════════════════
 * Text Input
 * ═══════════════════════════════════════════ */

#define UI_MAX_TEXTBUFS 32
#define UI_TEXTBUF_SIZE 4096

static char ui_textbufs[UI_MAX_TEXTBUFS][UI_TEXTBUF_SIZE];
static int ui_textbuf_lens[UI_MAX_TEXTBUFS];
static int ui_textbuf_cursors[UI_MAX_TEXTBUFS];

void tsuchi_ui_textInput(const char *id, double buf_id, double w, double size) {
    int b = (int)buf_id;
    if (b < 0 || b >= UI_MAX_TEXTBUFS) return;

    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);

    /* Click to focus */
    if (hover && IsMouseButtonPressed(0)) {
        ui_focus_index = ui_focus_count;
        focused = 1;
    }

    /* Handle input when focused */
    if (focused) {
        int ch = GetCharPressed();
        while (ch >= 32) {
            if (ui_textbuf_lens[b] < UI_TEXTBUF_SIZE - 1) {
                int cur = ui_textbuf_cursors[b];
                /* Shift right */
                memmove(&ui_textbufs[b][cur + 1], &ui_textbufs[b][cur],
                        ui_textbuf_lens[b] - cur);
                ui_textbufs[b][cur] = (char)ch;
                ui_textbuf_lens[b]++;
                ui_textbuf_cursors[b]++;
            }
            ch = GetCharPressed();
        }
        if (IsKeyPressed(KEY_BACKSPACE) && ui_textbuf_cursors[b] > 0) {
            int cur = ui_textbuf_cursors[b];
            memmove(&ui_textbufs[b][cur - 1], &ui_textbufs[b][cur],
                    ui_textbuf_lens[b] - cur);
            ui_textbuf_lens[b]--;
            ui_textbuf_cursors[b]--;
        }
        if (IsKeyPressed(KEY_DELETE) && ui_textbuf_cursors[b] < ui_textbuf_lens[b]) {
            int cur = ui_textbuf_cursors[b];
            memmove(&ui_textbufs[b][cur], &ui_textbufs[b][cur + 1],
                    ui_textbuf_lens[b] - cur - 1);
            ui_textbuf_lens[b]--;
        }
        if (IsKeyPressed(KEY_LEFT) && ui_textbuf_cursors[b] > 0)
            ui_textbuf_cursors[b]--;
        if (IsKeyPressed(KEY_RIGHT) && ui_textbuf_cursors[b] < ui_textbuf_lens[b])
            ui_textbuf_cursors[b]++;
        if (IsKeyPressed(KEY_HOME)) ui_textbuf_cursors[b] = 0;
        if (IsKeyPressed(KEY_END)) ui_textbuf_cursors[b] = ui_textbuf_lens[b];
    }

    /* Render */
    int bgR = 36, bgG = 36, bgB = 48;
    if (focused) { bgR = 60; bgG = 60; bgB = 80; }

    int th = (int)size + 8;
    tsuchi_clay_open(id, (int)w, th, 4, 8, 4, 8, 0, 0, bgR, bgG, bgB, 255, 4);

    /* Display buffer with cursor at correct position */
    if (focused) {
        int cur = ui_textbuf_cursors[b];
        /* Text before cursor */
        if (cur > 0) {
            char before[UI_TEXTBUF_SIZE];
            memcpy(before, ui_textbufs[b], cur);
            before[cur] = '\0';
            tsuchi_clay_text(before, (int)size, 0, 230, 230, 240, 255);
        }
        /* Blinking cursor */
        if ((ui_frame_counter / 30) % 2 == 0) {
            tsuchi_clay_text("|", (int)size, 0, 120, 180, 255, 255);
        }
        /* Text after cursor */
        if (cur < ui_textbuf_lens[b]) {
            char after[UI_TEXTBUF_SIZE];
            int rem = ui_textbuf_lens[b] - cur;
            memcpy(after, ui_textbufs[b] + cur, rem);
            after[rem] = '\0';
            tsuchi_clay_text(after, (int)size, 0, 230, 230, 240, 255);
        }
    } else if (ui_textbuf_lens[b] > 0) {
        char tmp[UI_TEXTBUF_SIZE];
        memcpy(tmp, ui_textbufs[b], ui_textbuf_lens[b]);
        tmp[ui_textbuf_lens[b]] = '\0';
        tsuchi_clay_text(tmp, (int)size, 0, 230, 230, 240, 255);
    }

    tsuchi_clay_close();
    ui_register_focusable();

    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = 0;
}

/* ═══════════════════════════════════════════
 * Slider
 * ═══════════════════════════════════════════ */

void tsuchi_ui_slider(const char *id, double value, double min_val,
                       double max_val, double w) {
    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);
    double range = max_val - min_val;
    double new_val = value;

    /* Background */
    int bgR = 36, bgG = 36, bgB = 48;
    if (hover || focused) { bgR = 50; bgG = 50; bgB = 68; }

    int h = 16;
    tsuchi_clay_open(id, (int)w, h, 0, 0, 0, 0, 0, 0, bgR, bgG, bgB, 255, 4);

    /* Fill */
    if (range > 0) {
        int fill_w = (int)((value - min_val) * w / range);
        if (fill_w < 0) fill_w = 0;
        if (fill_w > (int)w) fill_w = (int)w;
        if (fill_w > 0) {
            int fr = focused ? 80 : 60;
            int fg = focused ? 140 : 100;
            int fb = focused ? 220 : 180;
            tsuchi_clay_open("", fill_w, h, 0, 0, 0, 0, 0, 0, fr, fg, fb, 255, 4);
            tsuchi_clay_close();
        }
    }

    tsuchi_clay_close();

    /* Click: increment by 5% */
    if (hover && IsMouseButtonPressed(0)) {
        double step = range / 20.0;
        if (step < 1) step = 1;
        new_val = value + step;
        if (new_val > max_val) new_val = max_val;
        ui_focus_index = ui_focus_count;
    }

    /* Keyboard */
    if (focused) {
        double step = range / 20.0;
        if (step < 1) step = 1;
        if (IsKeyPressed(KEY_RIGHT)) {
            new_val = value + step;
            if (new_val > max_val) new_val = max_val;
        }
        if (IsKeyPressed(KEY_LEFT)) {
            new_val = value - step;
            if (new_val < min_val) new_val = min_val;
        }
    }

    ui_register_focusable();
    ui_widget_hovered[idx] = hover;
    ui_widget_slider_val[idx] = new_val;
}

/* ═══════════════════════════════════════════
 * Menu Item
 * ═══════════════════════════════════════════ */

void tsuchi_ui_menuItemOpen(const char *id, double index, double cursor, double size) {
    int idx = ui_find_or_add_widget(id);
    int hover = tsuchi_clay_pointer_over(id);
    int is_selected = (int)index == (int)cursor;

    int bgR = 0, bgG = 0, bgB = 0, bgA = 0;
    if (is_selected) { bgR = 60; bgG = 100; bgB = 180; bgA = 255; }
    else if (hover)  { bgR = 60; bgG = 60; bgB = 80; bgA = 255; }

    tsuchi_clay_open(id, -1, 0, 2, 8, 2, 8, 4, 0, bgR, bgG, bgB, bgA, 0);

    if (is_selected) {
        tsuchi_clay_text("> ", (int)size, 0, 255, 255, 100, 255);
    } else {
        tsuchi_clay_text("  ", (int)size, 0, 255, 255, 255, 255);
    }

    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = hover && IsMouseButtonPressed(0);
}

void tsuchi_ui_menuItemClose(void) {
    tsuchi_clay_close();
}

/* ═══════════════════════════════════════════
 * Tab Button
 * ═══════════════════════════════════════════ */

void tsuchi_ui_tabButtonOpen(const char *id, double index, double active, double size) {
    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);
    int is_active = (int)index == (int)active;

    int bgR = 36, bgG = 36, bgB = 48;
    if (is_active) { bgR = 60; bgG = 100; bgB = 180; }
    else if (hover || focused) { bgR = 60; bgG = 60; bgB = 80; }

    tsuchi_clay_open(id, 0, 0, 6, 12, 6, 12, 0, 0, bgR, bgG, bgB, 255, 0);

    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = ui_detect_click(id);
}

void tsuchi_ui_tabButtonClose(void) {
    tsuchi_clay_close();
    ui_register_focusable();
}

/* ═══════════════════════════════════════════
 * Number Stepper
 * ═══════════════════════════════════════════ */

void tsuchi_ui_numberStepper(const char *id, double value, double min_val,
                              double max_val, double size) {
    int idx = ui_find_or_add_widget(id);

    tsuchi_clay_open(id, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0);

    /* Minus button */
    char minus_id[128];
    snprintf(minus_id, sizeof(minus_id), "%s_m", id);
    int can_dec = value > min_val;
    int mr = can_dec ? 60 : 36, mg = can_dec ? 100 : 36, mb = can_dec ? 180 : 48;
    tsuchi_clay_open(minus_id, 0, 0, 2, 6, 2, 6, 0, 0, mr, mg, mb, 255, 0);
    tsuchi_clay_text("-", (int)size, 0, 255, 255, 255, 255);
    tsuchi_clay_close();

    /* Value display */
    char val_buf[32];
    snprintf(val_buf, sizeof(val_buf), " %d ", (int)value);
    tsuchi_clay_text(val_buf, (int)size, 0, 230, 230, 240, 255);

    /* Plus button */
    char plus_id[128];
    snprintf(plus_id, sizeof(plus_id), "%s_p", id);
    int can_inc = value < max_val;
    int pr = can_inc ? 60 : 36, pg = can_inc ? 100 : 36, pb = can_inc ? 180 : 48;
    tsuchi_clay_open(plus_id, 0, 0, 2, 6, 2, 6, 0, 0, pr, pg, pb, 255, 0);
    tsuchi_clay_text("+", (int)size, 0, 255, 255, 255, 255);
    tsuchi_clay_close();

    tsuchi_clay_close();

    /* Detect clicks on minus/plus */
    double new_val = value;
    if (can_dec && tsuchi_clay_pointer_over(minus_id) && IsMouseButtonPressed(0)) {
        new_val = value - 1;
    }
    if (can_inc && tsuchi_clay_pointer_over(plus_id) && IsMouseButtonPressed(0)) {
        new_val = value + 1;
    }

    ui_widget_slider_val[idx] = new_val;
    ui_register_focusable();
}

/* ═══════════════════════════════════════════
 * Search Bar
 * ═══════════════════════════════════════════ */

void tsuchi_ui_searchBar(const char *id, double buf_id, double w, double size) {
    /* Wrapper: search icon + text input */
    char outer_id[128];
    snprintf(outer_id, sizeof(outer_id), "%s_sb", id);
    tsuchi_clay_open(outer_id, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0);
    tsuchi_clay_text("[?] ", (int)size, 0, 80, 80, 100, 255);
    tsuchi_ui_textInput(id, buf_id, w, size);
    tsuchi_clay_close();
}

/* ═══════════════════════════════════════════
 * List Item
 * ═══════════════════════════════════════════ */

void tsuchi_ui_listItemOpen(const char *id, double index, double selected, double size) {
    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);
    int is_selected = (int)index == (int)selected;

    int bgR = 0, bgG = 0, bgB = 0, bgA = 0;
    if (is_selected) { bgR = 60; bgG = 100; bgB = 180; bgA = 255; }
    else if (hover || focused) { bgR = 60; bgG = 60; bgB = 80; bgA = 255; }

    tsuchi_clay_open(id, -1, 0, 2, 8, 2, 8, 4, 0, bgR, bgG, bgB, bgA, 0);

    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = ui_detect_click(id);
}

void tsuchi_ui_listItemClose(void) {
    tsuchi_clay_close();
    ui_register_focusable();
}

/* ═══════════════════════════════════════════
 * Switch (visual toggle [O  ]/[  O])
 * ═══════════════════════════════════════════ */

void tsuchi_ui_switchOpen(const char *id, double on, double size) {
    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);
    int bgR = 36, bgG = 36, bgB = 48;
    if (hover || focused) { bgR = 60; bgG = 60; bgB = 80; }

    tsuchi_clay_open(id, 0, 0, 2, 4, 2, 8, 6, 0, bgR, bgG, bgB, 255, 0);

    if ((int)on) {
        tsuchi_clay_open("", 48, (int)size + 4, 2, 2, 2, 2, 0, 0, 80, 200, 120, 255, 8);
        tsuchi_clay_open("", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
        tsuchi_clay_close();  /* spacer */
        tsuchi_clay_open("", (int)size, (int)size, 0, 0, 0, 0, 0, 0, 255, 255, 255, 255, (int)size);
        tsuchi_clay_close();  /* knob */
        tsuchi_clay_close();  /* track */
    } else {
        tsuchi_clay_open("", 48, (int)size + 4, 2, 2, 2, 2, 0, 0, 80, 80, 100, 255, 8);
        tsuchi_clay_open("", (int)size, (int)size, 0, 0, 0, 0, 0, 0, 200, 200, 210, 255, (int)size);
        tsuchi_clay_close();  /* knob */
        tsuchi_clay_close();  /* track */
    }

    ui_widget_hovered[idx] = hover;
    int click = ui_detect_click(id);
    ui_widget_clicked[idx] = click;
    ui_widget_toggled[idx] = click;
}

void tsuchi_ui_switchClose(void) {
    tsuchi_clay_close();
    ui_register_focusable();
}

/* ═══════════════════════════════════════════
 * Rating (star display ★★★☆☆)
 * ═══════════════════════════════════════════ */

void tsuchi_ui_ratingOpen(const char *id, double value, double max_val, double size) {
    int idx = ui_find_or_add_widget(id);
    int hover = tsuchi_clay_pointer_over(id);

    tsuchi_clay_open(id, 0, 0, 2, 4, 2, 4, 2, 0, 0, 0, 0, 0, 0);

    int imax = (int)max_val;
    int ival = (int)value;
    for (int i = 0; i < imax; i++) {
        if (i < ival) {
            tsuchi_clay_text("*", (int)size, 0, 255, 200, 50, 255);
        } else {
            tsuchi_clay_text("*", (int)size, 0, 80, 80, 100, 255);
        }
    }

    /* Detect click to change rating */
    if (hover && IsMouseButtonPressed(0)) {
        /* Simple: clicking increments or wraps */
        double new_val = value + 1;
        if (new_val > max_val) new_val = 0;
        ui_widget_slider_val[idx] = new_val;
    } else {
        ui_widget_slider_val[idx] = value;
    }

    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = hover && IsMouseButtonPressed(0);
}

void tsuchi_ui_ratingClose(void) {
    tsuchi_clay_close();
    ui_register_focusable();
}

/* ═══════════════════════════════════════════
 * Segment Button
 * ═══════════════════════════════════════════ */

void tsuchi_ui_segmentButtonOpen(const char *id, double index, double active, double size) {
    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);
    int is_active = (int)index == (int)active;

    int bgR = 50, bgG = 50, bgB = 64;
    if (is_active) { bgR = 60; bgG = 100; bgB = 180; }
    else if (hover || focused) { bgR = 60; bgG = 60; bgB = 80; }

    tsuchi_clay_open(id, 0, 0, 6, 12, 6, 12, 0, 0, bgR, bgG, bgB, 255, 0);

    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = ui_detect_click(id);
}

void tsuchi_ui_segmentButtonClose(void) {
    tsuchi_clay_close();
    ui_register_focusable();
}

/* ═══════════════════════════════════════════
 * Textarea (multi-line text input)
 * ═══════════════════════════════════════════ */

void tsuchi_ui_textareaInput(const char *id, double buf_id, double w, double h, double size) {
    int b = (int)buf_id;
    if (b < 0 || b >= UI_MAX_TEXTBUFS) return;

    int idx = ui_find_or_add_widget(id);
    int focused = ui_is_focused();
    int hover = tsuchi_clay_pointer_over(id);

    if (hover && IsMouseButtonPressed(0)) {
        ui_focus_index = ui_focus_count;
        focused = 1;
    }

    if (focused) {
        int ch = GetCharPressed();
        while (ch >= 32) {
            if (ui_textbuf_lens[b] < UI_TEXTBUF_SIZE - 1) {
                int cur = ui_textbuf_cursors[b];
                memmove(&ui_textbufs[b][cur + 1], &ui_textbufs[b][cur],
                        ui_textbuf_lens[b] - cur);
                ui_textbufs[b][cur] = (char)ch;
                ui_textbuf_lens[b]++;
                ui_textbuf_cursors[b]++;
            }
            ch = GetCharPressed();
        }
        /* Newline on Enter */
        if (IsKeyPressed(KEY_ENTER) && ui_textbuf_lens[b] < UI_TEXTBUF_SIZE - 1) {
            int cur = ui_textbuf_cursors[b];
            memmove(&ui_textbufs[b][cur + 1], &ui_textbufs[b][cur],
                    ui_textbuf_lens[b] - cur);
            ui_textbufs[b][cur] = '\n';
            ui_textbuf_lens[b]++;
            ui_textbuf_cursors[b]++;
        }
        if (IsKeyPressed(KEY_BACKSPACE) && ui_textbuf_cursors[b] > 0) {
            int cur = ui_textbuf_cursors[b];
            memmove(&ui_textbufs[b][cur - 1], &ui_textbufs[b][cur],
                    ui_textbuf_lens[b] - cur);
            ui_textbuf_lens[b]--;
            ui_textbuf_cursors[b]--;
        }
        if (IsKeyPressed(KEY_DELETE) && ui_textbuf_cursors[b] < ui_textbuf_lens[b]) {
            int cur = ui_textbuf_cursors[b];
            memmove(&ui_textbufs[b][cur], &ui_textbufs[b][cur + 1],
                    ui_textbuf_lens[b] - cur - 1);
            ui_textbuf_lens[b]--;
        }
        if (IsKeyPressed(KEY_LEFT) && ui_textbuf_cursors[b] > 0)
            ui_textbuf_cursors[b]--;
        if (IsKeyPressed(KEY_RIGHT) && ui_textbuf_cursors[b] < ui_textbuf_lens[b])
            ui_textbuf_cursors[b]++;
        if (IsKeyPressed(KEY_HOME)) ui_textbuf_cursors[b] = 0;
        if (IsKeyPressed(KEY_END)) ui_textbuf_cursors[b] = ui_textbuf_lens[b];
    }

    int bgR = 36, bgG = 36, bgB = 48;
    if (focused) { bgR = 60; bgG = 60; bgB = 80; }

    tsuchi_clay_open(id, (int)w, (int)h, 4, 8, 4, 8, 0, 1, bgR, bgG, bgB, 255, 4);

    if (focused) {
        int cur = ui_textbuf_cursors[b];
        if (cur > 0) {
            char before[UI_TEXTBUF_SIZE];
            memcpy(before, ui_textbufs[b], cur);
            before[cur] = '\0';
            tsuchi_clay_text(before, (int)size, 0, 230, 230, 240, 255);
        }
        if ((ui_frame_counter / 30) % 2 == 0) {
            tsuchi_clay_text("|", (int)size, 0, 120, 180, 255, 255);
        }
        if (cur < ui_textbuf_lens[b]) {
            char after[UI_TEXTBUF_SIZE];
            int rem = ui_textbuf_lens[b] - cur;
            memcpy(after, ui_textbufs[b] + cur, rem);
            after[rem] = '\0';
            tsuchi_clay_text(after, (int)size, 0, 230, 230, 240, 255);
        }
    } else if (ui_textbuf_lens[b] > 0) {
        char tmp[UI_TEXTBUF_SIZE];
        memcpy(tmp, ui_textbufs[b], ui_textbuf_lens[b]);
        tmp[ui_textbuf_lens[b]] = '\0';
        tsuchi_clay_text(tmp, (int)size, 0, 230, 230, 240, 255);
    }

    tsuchi_clay_close();
    ui_register_focusable();

    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = 0;
}

/* ═══════════════════════════════════════════
 * Navigation Stack
 * ═══════════════════════════════════════════ */

#define UI_NAV_MAX_DEPTH 8
static int ui_nav_stack[UI_NAV_MAX_DEPTH];
static int ui_nav_depth = 0;

void tsuchi_ui_navPush(double scene) {
    if (ui_nav_depth < UI_NAV_MAX_DEPTH) {
        ui_nav_stack[ui_nav_depth++] = (int)scene;
    }
}

void tsuchi_ui_navPop(void) {
    if (ui_nav_depth > 0) {
        ui_nav_depth--;
    }
}

double tsuchi_ui_navCurrent(void) {
    if (ui_nav_depth > 0) {
        return (double)ui_nav_stack[ui_nav_depth - 1];
    }
    return 0.0;
}

double tsuchi_ui_navDepth(void) {
    return (double)ui_nav_depth;
}

/* ═══════════════════════════════════════════
 * Accordion
 * ═══════════════════════════════════════════ */

void tsuchi_ui_accordionOpen(const char *id, double expanded) {
    int idx = ui_find_or_add_widget(id);
    int hover = tsuchi_clay_pointer_over(id);

    int bgR = 36, bgG = 36, bgB = 48;
    if (hover) { bgR = 50; bgG = 50; bgB = 64; }

    tsuchi_clay_open(id, -1, 0, 4, 8, 4, 8, 4, 1, bgR, bgG, bgB, 255, 4);

    /* Header bar */
    const char *arrow = (int)expanded ? "v " : "> ";
    tsuchi_clay_text(arrow, 16, 0, 120, 180, 255, 255);

    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = hover && IsMouseButtonPressed(0);
    ui_widget_toggled[idx] = ui_widget_clicked[idx];
}

void tsuchi_ui_accordionClose(void) {
    tsuchi_clay_close();
}

/* ═══════════════════════════════════════════
 * Dropdown
 * ═══════════════════════════════════════════ */

#define UI_MAX_DROPDOWNS 16
static unsigned int ui_dropdown_hashes[UI_MAX_DROPDOWNS];
static int ui_dropdown_open[UI_MAX_DROPDOWNS];
static int ui_dropdown_count = 0;

static int ui_dropdown_find_or_add(const char *id) {
    unsigned int h = ui_hash_str(id);
    for (int i = 0; i < ui_dropdown_count; i++) {
        if (ui_dropdown_hashes[i] == h) return i;
    }
    if (ui_dropdown_count >= UI_MAX_DROPDOWNS) return 0;
    int idx = ui_dropdown_count++;
    ui_dropdown_hashes[idx] = h;
    ui_dropdown_open[idx] = 0;
    return idx;
}

void tsuchi_ui_dropdownOpen(const char *id) {
    int idx = ui_find_or_add_widget(id);
    int dd = ui_dropdown_find_or_add(id);
    int hover = tsuchi_clay_pointer_over(id);

    int bgR = 36, bgG = 36, bgB = 48;
    if (hover) { bgR = 50; bgG = 50; bgB = 64; }

    tsuchi_clay_open(id, 0, 0, 4, 8, 4, 8, 4, 1, bgR, bgG, bgB, 255, 4);

    if (hover && IsMouseButtonPressed(0)) {
        ui_dropdown_open[dd] = !ui_dropdown_open[dd];
    }

    ui_widget_hovered[idx] = hover;
    ui_widget_clicked[idx] = hover && IsMouseButtonPressed(0);
}

void tsuchi_ui_dropdownClose(void) {
    tsuchi_clay_close();
}

int tsuchi_ui_dropdownIsOpen(const char *id) {
    int dd = ui_dropdown_find_or_add(id);
    return ui_dropdown_open[dd];
}

/* ═══════════════════════════════════════════
 * Tooltip
 * ═══════════════════════════════════════════ */

void tsuchi_ui_tooltipBegin(const char *id) {
    int idx = ui_find_or_add_widget(id);
    tsuchi_clay_open(id, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    ui_widget_hovered[idx] = tsuchi_clay_pointer_over(id);
}

void tsuchi_ui_tooltipEnd(void) {
    tsuchi_clay_close();
}

/* ═══════════════════════════════════════════
 * Toast
 * ═══════════════════════════════════════════ */

#define UI_MAX_TOASTS 8
#define UI_TOAST_BUF_SIZE 256
static char ui_toast_msgs[UI_MAX_TOASTS][UI_TOAST_BUF_SIZE];
static int ui_toast_kinds[UI_MAX_TOASTS];
static int ui_toast_frames[UI_MAX_TOASTS];  /* frames remaining */
static int ui_toast_count = 0;

void tsuchi_ui_toastShow(const char *msg, double kind, double duration_sec) {
    if (ui_toast_count >= UI_MAX_TOASTS) {
        /* Shift queue */
        memmove(&ui_toast_msgs[0], &ui_toast_msgs[1], (UI_MAX_TOASTS - 1) * UI_TOAST_BUF_SIZE);
        memmove(&ui_toast_kinds[0], &ui_toast_kinds[1], (UI_MAX_TOASTS - 1) * sizeof(int));
        memmove(&ui_toast_frames[0], &ui_toast_frames[1], (UI_MAX_TOASTS - 1) * sizeof(int));
        ui_toast_count = UI_MAX_TOASTS - 1;
    }
    int i = ui_toast_count++;
    strncpy(ui_toast_msgs[i], msg, UI_TOAST_BUF_SIZE - 1);
    ui_toast_msgs[i][UI_TOAST_BUF_SIZE - 1] = '\0';
    ui_toast_kinds[i] = (int)kind;
    ui_toast_frames[i] = (int)(duration_sec * 60);  /* assume 60fps */
}

void tsuchi_ui_toastRender(void) {
    int write = 0;
    for (int i = 0; i < ui_toast_count; i++) {
        ui_toast_frames[i]--;
        if (ui_toast_frames[i] <= 0) continue;

        int r = 60, g = 100, b = 180;
        switch (ui_toast_kinds[i]) {
            case 1: r = 80; g = 200; b = 120; break;  /* success */
            case 2: r = 220; g = 180; b = 80; break;   /* warning */
            case 3: r = 220; g = 80; b = 80; break;    /* error */
        }

        tsuchi_clay_open("", 0, 0, 8, 16, 8, 16, 0, 0, r, g, b, 230, 8);
        tsuchi_clay_text(ui_toast_msgs[i], 14, 0, 255, 255, 255, 255);
        tsuchi_clay_close();

        if (write != i) {
            memcpy(ui_toast_msgs[write], ui_toast_msgs[i], UI_TOAST_BUF_SIZE);
            ui_toast_kinds[write] = ui_toast_kinds[i];
            ui_toast_frames[write] = ui_toast_frames[i];
        }
        write++;
    }
    ui_toast_count = write;
}

/* ═══════════════════════════════════════════
 * Charts (simple bar/line/pie via Clay boxes)
 * ═══════════════════════════════════════════ */

#define UI_MAX_CHARTS 8
#define UI_CHART_MAX_POINTS 32

static struct {
    unsigned int hash;
    int type;   /* 0=bar, 1=line, 2=pie */
    int count;
    double max_val;
    double values[UI_CHART_MAX_POINTS];
    int colors[UI_CHART_MAX_POINTS][3];
} ui_charts[UI_MAX_CHARTS];
static int ui_chart_count = 0;

static int ui_chart_find_or_add(const char *id) {
    unsigned int h = ui_hash_str(id);
    for (int i = 0; i < ui_chart_count; i++) {
        if (ui_charts[i].hash == h) return i;
    }
    if (ui_chart_count >= UI_MAX_CHARTS) return 0;
    int idx = ui_chart_count++;
    ui_charts[idx].hash = h;
    ui_charts[idx].type = 0;
    ui_charts[idx].count = 0;
    ui_charts[idx].max_val = 100;
    for (int j = 0; j < UI_CHART_MAX_POINTS; j++) {
        ui_charts[idx].values[j] = 0;
        ui_charts[idx].colors[j][0] = 60;
        ui_charts[idx].colors[j][1] = 100;
        ui_charts[idx].colors[j][2] = 180;
    }
    return idx;
}

void tsuchi_ui_chartInit(const char *id, double type, double count, double max_val) {
    int c = ui_chart_find_or_add(id);
    ui_charts[c].type = (int)type;
    ui_charts[c].count = (int)count;
    if (ui_charts[c].count > UI_CHART_MAX_POINTS) ui_charts[c].count = UI_CHART_MAX_POINTS;
    ui_charts[c].max_val = max_val;
}

void tsuchi_ui_chartSet(const char *id, double idx, double val) {
    int c = ui_chart_find_or_add(id);
    int i = (int)idx;
    if (i >= 0 && i < ui_charts[c].count) {
        ui_charts[c].values[i] = val;
    }
}

void tsuchi_ui_chartColor(const char *id, double idx, double r, double g, double b) {
    int c = ui_chart_find_or_add(id);
    int i = (int)idx;
    if (i >= 0 && i < ui_charts[c].count) {
        ui_charts[c].colors[i][0] = (int)r;
        ui_charts[c].colors[i][1] = (int)g;
        ui_charts[c].colors[i][2] = (int)b;
    }
}

void tsuchi_ui_chartRender(const char *id, double type, double count, double max_val, double w, double h) {
    int c = ui_chart_find_or_add(id);
    ui_charts[c].type = (int)type;
    if ((int)count > 0) ui_charts[c].count = ui_min((int)count, UI_CHART_MAX_POINTS);
    if (max_val > 0) ui_charts[c].max_val = max_val;

    int iw = (int)w;
    int ih = (int)h;
    int n = ui_charts[c].count;
    if (n <= 0) n = 1;

    tsuchi_clay_open(id, iw, ih, 2, 2, 2, 2, 1, 0, 30, 30, 40, 255, 4);

    if (ui_charts[c].type == 0) {
        /* Bar chart */
        int bar_w = (iw - 4 - (n - 1)) / n;
        if (bar_w < 2) bar_w = 2;
        for (int i = 0; i < n; i++) {
            double frac = ui_charts[c].max_val > 0 ? ui_charts[c].values[i] / ui_charts[c].max_val : 0;
            if (frac > 1.0) frac = 1.0;
            if (frac < 0.0) frac = 0.0;
            int bar_h = (int)(frac * (ih - 4));
            if (bar_h < 1) bar_h = 1;
            /* Spacer above + bar */
            tsuchi_clay_open("", bar_w, ih - 4, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0);
            tsuchi_clay_open("", bar_w, ih - 4 - bar_h, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
            tsuchi_clay_close();
            tsuchi_clay_open("", bar_w, bar_h, 0, 0, 0, 0, 0, 0,
                ui_charts[c].colors[i][0], ui_charts[c].colors[i][1], ui_charts[c].colors[i][2], 255, 2);
            tsuchi_clay_close();
            tsuchi_clay_close();
        }
    } else if (ui_charts[c].type == 1) {
        /* Line chart — show as bars with thinner width */
        int bar_w = (iw - 4 - (n - 1)) / n;
        if (bar_w < 2) bar_w = 2;
        for (int i = 0; i < n; i++) {
            double frac = ui_charts[c].max_val > 0 ? ui_charts[c].values[i] / ui_charts[c].max_val : 0;
            if (frac > 1.0) frac = 1.0;
            if (frac < 0.0) frac = 0.0;
            int dot_y = (int)((1.0 - frac) * (ih - 8));
            tsuchi_clay_open("", 2, ih - 4, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0);
            tsuchi_clay_open("", 2, dot_y, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
            tsuchi_clay_close();
            tsuchi_clay_open("", 4, 4, 0, 0, 0, 0, 0, 0,
                ui_charts[c].colors[i][0], ui_charts[c].colors[i][1], ui_charts[c].colors[i][2], 255, 4);
            tsuchi_clay_close();
            tsuchi_clay_close();
        }
    } else {
        /* Pie chart — show as text representation */
        char pie_buf[128];
        snprintf(pie_buf, sizeof(pie_buf), "[Pie: %d items]", n);
        tsuchi_clay_text(pie_buf, 14, 0, 180, 180, 200, 255);
    }

    tsuchi_clay_close();
}

/* ═══════════════════════════════════════════
 * Markdown (simple parser → Clay text)
 * ═══════════════════════════════════════════ */

void tsuchi_ui_markdownRender(const char *text, double w, double size) {
    int isize = (int)size;
    int iw = (int)w;
    if (iw <= 0) iw = -1;  /* GROW */

    tsuchi_clay_open("", iw, 0, 0, 0, 0, 0, 4, 1, 0, 0, 0, 0, 0);

    const char *p = text;
    char line_buf[1024];

    while (*p) {
        /* Read one line */
        int len = 0;
        while (p[len] && p[len] != '\n' && len < 1023) len++;
        memcpy(line_buf, p, len);
        line_buf[len] = '\0';
        p += len;
        if (*p == '\n') p++;

        /* Skip empty lines */
        if (len == 0) {
            tsuchi_clay_open("", -1, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
            tsuchi_clay_close();
            continue;
        }

        /* Heading */
        if (line_buf[0] == '#') {
            int level = 0;
            while (line_buf[level] == '#' && level < 6) level++;
            const char *htext = line_buf + level;
            while (*htext == ' ') htext++;
            int hsizes[] = {32, 28, 24, 20, 18, 16};
            int hs = level >= 1 && level <= 6 ? hsizes[level - 1] : isize;
            tsuchi_clay_text(htext, hs, 0, 255, 255, 255, 255);
            continue;
        }

        /* Code block start/end */
        if (len >= 3 && line_buf[0] == '`' && line_buf[1] == '`' && line_buf[2] == '`') {
            /* Just skip the delimiter lines */
            continue;
        }

        /* Block quote */
        if (line_buf[0] == '>') {
            const char *qtext = line_buf + 1;
            while (*qtext == ' ') qtext++;
            tsuchi_clay_open("", -1, 0, 2, 8, 2, 8, 0, 0, 50, 50, 64, 255, 0);
            tsuchi_clay_text(qtext, isize, 0, 180, 180, 200, 255);
            tsuchi_clay_close();
            continue;
        }

        /* List item */
        if ((line_buf[0] == '-' || line_buf[0] == '*') && line_buf[1] == ' ') {
            const char *ltext = line_buf + 2;
            tsuchi_clay_open("", -1, 0, 1, 0, 1, 8, 4, 0, 0, 0, 0, 0, 0);
            tsuchi_clay_text("* ", isize, 0, 120, 180, 255, 255);
            tsuchi_clay_text(ltext, isize, 0, 230, 230, 240, 255);
            tsuchi_clay_close();
            continue;
        }

        /* Regular paragraph */
        tsuchi_clay_text(line_buf, isize, 0, 230, 230, 240, 255);
    }

    tsuchi_clay_close();
}

/* ═══════════════════════════════════════════
 * Spinner
 * ═══════════════════════════════════════════ */

const char* tsuchi_ui_spinnerChar(void) {
    static const char *frames[] = {"-", "\\", "|", "/"};
    return frames[(ui_frame_counter / 10) % 4];
}

/* ═══════════════════════════════════════════
 * Frame counter accessor
 * ═══════════════════════════════════════════ */

double tsuchi_ui_frameCount(void) {
    return (double)ui_frame_counter;
}

/* ═══════════════════════════════════════════
 * Style Composition (Konpeito-compatible)
 *
 * Packed integer: size + flex*1000 + kind*1000000
 *   size: 0-999 (font size)
 *   flex: 0-999 (width percentage, 0=FIT)
 *   kind: 0-4   (color variant)
 * ═══════════════════════════════════════════ */

double tsuchi_ui_style(double size, double kind, double flex) {
    return (double)((int)size + (int)flex * 1000 + (int)kind * 1000000);
}

double tsuchi_ui_styleMerge(double a, double b) {
    int ia = (int)a, ib = (int)b;
    int s = ib % 1000;
    if (s == 0) s = ia % 1000;
    int f = (ib / 1000) % 1000;
    if (f == 0) f = (ia / 1000) % 1000;
    int k = ib / 1000000;
    if (k == 0) k = ia / 1000000;
    return (double)(s + f * 1000 + k * 1000000);
}

double tsuchi_ui_styleSize(double s) { return (double)((int)s % 1000); }
double tsuchi_ui_styleKind(double s) { return (double)((int)s / 1000000); }
double tsuchi_ui_styleFlex(double s) { return (double)(((int)s / 1000) % 1000); }
