/*
 * Tsuchi Game Framework — C runtime helpers for 2D games
 *
 * Provides higher-level game utilities on top of raylib:
 * math, drawing, input, animation, timers, tweens, easing,
 * screen effects, scene transitions, physics, particles,
 * grid/tilemap, FSM, and object pools.
 *
 * All state is static (one instance per process).
 * All functions use f64 parameters (matching Tsuchi's number type).
 */

#include <math.h>
#include <string.h>
#include "raylib.h"

/* ═══════════════════════════════════════════
 * Section 1: Math Helpers
 * ═══════════════════════════════════════════ */

double tsuchi_gf_clamp(double v, double lo, double hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

double tsuchi_gf_lerp(double a, double b, double t) {
    return a + (b - a) * t;
}

/* LCG pseudo-random */
static unsigned int gf_rand_seed = 12345;

double tsuchi_gf_rand(double max_val) {
    gf_rand_seed = gf_rand_seed * 1103515245 + 12345;
    gf_rand_seed &= 0x7FFFFFFF;
    int m = (int)max_val;
    if (m <= 0) return 0;
    return (double)(gf_rand_seed % m);
}

double tsuchi_gf_randRange(double min_val, double max_val) {
    double range = max_val - min_val;
    if (range <= 0) return min_val;
    return min_val + tsuchi_gf_rand(range);
}

double tsuchi_gf_rgba(double r, double g, double b, double a) {
    unsigned int ri = (unsigned int)r & 0xFF;
    unsigned int gi = (unsigned int)g & 0xFF;
    unsigned int bi = (unsigned int)b & 0xFF;
    unsigned int ai = (unsigned int)a & 0xFF;
    return (double)((ri << 24) | (gi << 16) | (bi << 8) | ai);
}

/* ═══════════════════════════════════════════
 * Section 2: Drawing Helpers
 * ═══════════════════════════════════════════ */

static Color gf_unpack_color(double packed) {
    unsigned int c = (unsigned int)packed;
    return (Color){ (c >> 24) & 0xFF, (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF };
}

void tsuchi_gf_drawBar(double x, double y, double w, double h,
                       double val, double max_val, double fg, double bg_col) {
    Color bg = gf_unpack_color(bg_col);
    Color fgc = gf_unpack_color(fg);
    DrawRectangle((int)x, (int)y, (int)w, (int)h, bg);
    if (max_val > 0) {
        int bw = (int)(val * w / max_val);
        if (bw < 0) bw = 0;
        if (bw > (int)w) bw = (int)w;
        if (bw > 0) DrawRectangle((int)x, (int)y, bw, (int)h, fgc);
    }
}

void tsuchi_gf_drawBox(double x, double y, double w, double h,
                       double bg_col, double border_col) {
    Color bg = gf_unpack_color(bg_col);
    Color border = gf_unpack_color(border_col);
    DrawRectangle((int)x, (int)y, (int)w, (int)h, bg);
    DrawRectangleLines((int)x, (int)y, (int)w, (int)h, border);
}

static void gf_draw_digit(int x, int y, int d, int sz, Color col) {
    char buf[2] = { '0' + d, '\0' };
    DrawText(buf, x, y, sz, col);
}

void tsuchi_gf_drawNum(double x, double y, double n, double sz, double col) {
    Color c = gf_unpack_color(col);
    int ix = (int)x, iy = (int)y, isz = (int)sz;
    int sp = isz * 6 / 10;
    int num = (int)n;
    if (num < 0) {
        DrawText("-", ix, iy, isz, c);
        ix += sp;
        num = -num;
    }
    if (num >= 10000) { gf_draw_digit(ix, iy, num / 10000, isz, c); ix += sp; }
    if (num >= 1000) { gf_draw_digit(ix, iy, (num / 1000) % 10, isz, c); ix += sp; }
    if (num >= 100) { gf_draw_digit(ix, iy, (num / 100) % 10, isz, c); ix += sp; }
    if (num >= 10) { gf_draw_digit(ix, iy, (num / 10) % 10, isz, c); ix += sp; }
    gf_draw_digit(ix, iy, num % 10, isz, c);
}

void tsuchi_gf_drawFPS(double x, double y, double sz, double col) {
    int fps = GetFPS();
    tsuchi_gf_drawNum(x, y, (double)fps, sz, col);
}

extern Texture2D _textures[];
extern int _tex_count;

void tsuchi_gf_drawTile(double texId, double tileId, double cols,
                        double srcSz, double dstSz, double dx, double dy) {
    int id = (int)texId;
    if (id < 0 || id >= _tex_count) return;
    int tile = (int)tileId;
    int c = (int)cols;
    int src = (int)srcSz;
    int sx = (tile % c) * src;
    int sy = (tile / c) * src;
    DrawTexturePro(_textures[id],
        (Rectangle){(float)sx, (float)sy, (float)src, (float)src},
        (Rectangle){(float)dx, (float)dy, (float)dstSz, (float)dstSz},
        (Vector2){0, 0}, 0.0f, WHITE);
}

void tsuchi_gf_drawSprite(double texId, double frame, double srcW, double srcH,
                          double dx, double dy, double dstW, double dstH) {
    int id = (int)texId;
    if (id < 0 || id >= _tex_count) return;
    int f = (int)frame;
    float sw = (float)srcW, sh = (float)srcH;
    DrawTexturePro(_textures[id],
        (Rectangle){(float)(f * (int)sw), 0.0f, sw, sh},
        (Rectangle){(float)dx, (float)dy, (float)dstW, (float)dstH},
        (Vector2){0, 0}, 0.0f, WHITE);
}

void tsuchi_gf_drawFade(double alpha, double w, double h) {
    int a = (int)alpha;
    if (a < 0) a = 0;
    if (a > 255) a = 255;
    DrawRectangle(0, 0, (int)w, (int)h, (Color){0, 0, 0, (unsigned char)a});
}

/* ═══════════════════════════════════════════
 * Section 3: Input Helpers
 * ═══════════════════════════════════════════ */

double tsuchi_gf_getDirection(void) {
    if (IsKeyDown(KEY_RIGHT)) return 0;
    if (IsKeyDown(KEY_UP))    return 1;
    if (IsKeyDown(KEY_LEFT))  return 2;
    if (IsKeyDown(KEY_DOWN))  return 3;
    return -1;
}

int tsuchi_gf_confirmPressed(void) {
    return IsKeyPressed(KEY_SPACE) || IsKeyPressed(KEY_ENTER) || IsKeyPressed(KEY_Z);
}

int tsuchi_gf_cancelPressed(void) {
    return IsKeyPressed(KEY_ESCAPE) || IsKeyPressed(KEY_X);
}

double tsuchi_gf_menuCursor(double cursor, double count) {
    int c = (int)cursor;
    int n = (int)count;
    if (n <= 0) return 0;
    if (IsKeyPressed(KEY_DOWN)) c++;
    if (IsKeyPressed(KEY_UP))   c--;
    if (c < 0) c = n - 1;
    if (c >= n) c = 0;
    return (double)c;
}

/* ═══════════════════════════════════════════
 * Section 4: Animation
 * ═══════════════════════════════════════════ */

static int gf_anim_counter = 0;

double tsuchi_gf_animate(double counter, double maxFrames, double speed) {
    gf_anim_counter++;
    int frame = (gf_anim_counter / (int)speed) % (int)maxFrames;
    return (double)frame;
}

/* ═══════════════════════════════════════════
 * Section 5: Timer System
 * ═══════════════════════════════════════════ */

#define GF_MAX_TIMERS 64

typedef struct {
    int active;
    double remaining;
    double interval;  /* >0 for repeating timers */
    int fired;        /* set to 1 when timer fires this tick */
} GfTimer;

static GfTimer gf_timers[GF_MAX_TIMERS];

void tsuchi_gf_timerSet(double slot, double duration) {
    int s = (int)slot;
    if (s < 0 || s >= GF_MAX_TIMERS) return;
    gf_timers[s].active = 1;
    gf_timers[s].remaining = duration;
    gf_timers[s].interval = 0;
    gf_timers[s].fired = 0;
}

void tsuchi_gf_timerRepeat(double slot, double interval) {
    int s = (int)slot;
    if (s < 0 || s >= GF_MAX_TIMERS) return;
    gf_timers[s].active = 1;
    gf_timers[s].remaining = interval;
    gf_timers[s].interval = interval;
    gf_timers[s].fired = 0;
}

void tsuchi_gf_timerTick(double dt) {
    for (int i = 0; i < GF_MAX_TIMERS; i++) {
        gf_timers[i].fired = 0;
        if (!gf_timers[i].active) continue;
        gf_timers[i].remaining -= dt;
        if (gf_timers[i].remaining <= 0) {
            gf_timers[i].fired = 1;
            if (gf_timers[i].interval > 0) {
                gf_timers[i].remaining += gf_timers[i].interval;
            } else {
                gf_timers[i].active = 0;
            }
        }
    }
}

int tsuchi_gf_timerActive(double slot) {
    int s = (int)slot;
    if (s < 0 || s >= GF_MAX_TIMERS) return 0;
    return gf_timers[s].active;
}

int tsuchi_gf_timerDone(double slot) {
    int s = (int)slot;
    if (s < 0 || s >= GF_MAX_TIMERS) return 0;
    return gf_timers[s].fired;
}

void tsuchi_gf_timerCancel(double slot) {
    int s = (int)slot;
    if (s < 0 || s >= GF_MAX_TIMERS) return;
    gf_timers[s].active = 0;
    gf_timers[s].fired = 0;
}

/* ═══════════════════════════════════════════
 * Section 6: Easing Functions
 * ═══════════════════════════════════════════ */

double tsuchi_gf_easeLinear(double t) { return t; }

double tsuchi_gf_easeInQuad(double t) { return t * t; }

double tsuchi_gf_easeOutQuad(double t) { return t * (2.0 - t); }

double tsuchi_gf_easeInOutQuad(double t) {
    if (t < 0.5) return 2.0 * t * t;
    return -1.0 + (4.0 - 2.0 * t) * t;
}

double tsuchi_gf_easeInCubic(double t) { return t * t * t; }

double tsuchi_gf_easeOutCubic(double t) {
    double u = t - 1.0;
    return u * u * u + 1.0;
}

double tsuchi_gf_easeInOutCubic(double t) {
    if (t < 0.5) return 4.0 * t * t * t;
    double u = 2.0 * t - 2.0;
    return 0.5 * u * u * u + 1.0;
}

double tsuchi_gf_easeOutBounce(double t) {
    if (t < 1.0 / 2.75) {
        return 7.5625 * t * t;
    } else if (t < 2.0 / 2.75) {
        t -= 1.5 / 2.75;
        return 7.5625 * t * t + 0.75;
    } else if (t < 2.5 / 2.75) {
        t -= 2.25 / 2.75;
        return 7.5625 * t * t + 0.9375;
    } else {
        t -= 2.625 / 2.75;
        return 7.5625 * t * t + 0.984375;
    }
}

double tsuchi_gf_easeOutElastic(double t) {
    if (t <= 0.0) return 0.0;
    if (t >= 1.0) return 1.0;
    return pow(2.0, -10.0 * t) * sin((t - 0.075) * (2.0 * 3.14159265358979323846) / 0.3) + 1.0;
}

double tsuchi_gf_interpolate(double start, double end, double t) {
    return start + (end - start) * t;
}

/* ═══════════════════════════════════════════
 * Section 7: Tween System
 * ═══════════════════════════════════════════ */

#define GF_MAX_TWEENS 32

typedef struct {
    int active;
    double elapsed;
    double duration;
    int easing;  /* 0=linear, 1=inQuad, 2=outQuad, 3=inOutQuad, 4=inCubic, 5=outCubic, 6=inOutCubic, 7=outBounce, 8=outElastic */
    int done;
} GfTween;

static GfTween gf_tweens[GF_MAX_TWEENS];

static double gf_apply_easing(int easing, double t) {
    switch (easing) {
        case 1: return tsuchi_gf_easeInQuad(t);
        case 2: return tsuchi_gf_easeOutQuad(t);
        case 3: return tsuchi_gf_easeInOutQuad(t);
        case 4: return tsuchi_gf_easeInCubic(t);
        case 5: return tsuchi_gf_easeOutCubic(t);
        case 6: return tsuchi_gf_easeInOutCubic(t);
        case 7: return tsuchi_gf_easeOutBounce(t);
        case 8: return tsuchi_gf_easeOutElastic(t);
        default: return t; /* linear */
    }
}

void tsuchi_gf_tweenStart(double slot, double duration, double easing) {
    int s = (int)slot;
    if (s < 0 || s >= GF_MAX_TWEENS) return;
    gf_tweens[s].active = 1;
    gf_tweens[s].elapsed = 0;
    gf_tweens[s].duration = duration;
    gf_tweens[s].easing = (int)easing;
    gf_tweens[s].done = 0;
}

void tsuchi_gf_tweenTick(double dt) {
    for (int i = 0; i < GF_MAX_TWEENS; i++) {
        gf_tweens[i].done = 0;
        if (!gf_tweens[i].active) continue;
        gf_tweens[i].elapsed += dt;
        if (gf_tweens[i].elapsed >= gf_tweens[i].duration) {
            gf_tweens[i].elapsed = gf_tweens[i].duration;
            gf_tweens[i].active = 0;
            gf_tweens[i].done = 1;
        }
    }
}

double tsuchi_gf_tweenValue(double slot) {
    int s = (int)slot;
    if (s < 0 || s >= GF_MAX_TWEENS) return 0;
    if (gf_tweens[s].duration <= 0) return 1.0;
    double t = gf_tweens[s].elapsed / gf_tweens[s].duration;
    if (t > 1.0) t = 1.0;
    return gf_apply_easing(gf_tweens[s].easing, t);
}

int tsuchi_gf_tweenActive(double slot) {
    int s = (int)slot;
    if (s < 0 || s >= GF_MAX_TWEENS) return 0;
    return gf_tweens[s].active;
}

int tsuchi_gf_tweenDone(double slot) {
    int s = (int)slot;
    if (s < 0 || s >= GF_MAX_TWEENS) return 0;
    return gf_tweens[s].done;
}

/* ═══════════════════════════════════════════
 * Section 8: Screen Shake
 * ═══════════════════════════════════════════ */

static double gf_shake_intensity = 0;
static double gf_shake_duration = 0;
static double gf_shake_elapsed = 0;
static double gf_shake_x = 0, gf_shake_y = 0;

void tsuchi_gf_shakeStart(double intensity, double duration) {
    gf_shake_intensity = intensity;
    gf_shake_duration = duration;
    gf_shake_elapsed = 0;
}

void tsuchi_gf_shakeUpdate(double dt) {
    if (gf_shake_elapsed >= gf_shake_duration) {
        gf_shake_x = 0;
        gf_shake_y = 0;
        return;
    }
    gf_shake_elapsed += dt;
    double remaining = 1.0 - gf_shake_elapsed / gf_shake_duration;
    if (remaining < 0) remaining = 0;
    double mag = gf_shake_intensity * remaining;
    /* Simple pseudo-random shake */
    gf_rand_seed = gf_rand_seed * 1103515245 + 12345;
    gf_shake_x = ((double)(gf_rand_seed % 200) - 100.0) / 100.0 * mag;
    gf_rand_seed = gf_rand_seed * 1103515245 + 12345;
    gf_shake_y = ((double)(gf_rand_seed % 200) - 100.0) / 100.0 * mag;
}

double tsuchi_gf_shakeX(void) { return gf_shake_x; }
double tsuchi_gf_shakeY(void) { return gf_shake_y; }
int tsuchi_gf_shakeActive(void) { return gf_shake_elapsed < gf_shake_duration; }

/* ═══════════════════════════════════════════
 * Section 9: Scene Transitions
 * ═══════════════════════════════════════════ */

static double gf_trans_duration = 0;
static double gf_trans_elapsed = 0;
static double gf_trans_next_scene = 0;
static int gf_trans_active = 0;

void tsuchi_gf_transitionStart(double duration, double nextScene) {
    gf_trans_duration = duration;
    gf_trans_elapsed = 0;
    gf_trans_next_scene = nextScene;
    gf_trans_active = 1;
}

void tsuchi_gf_transitionUpdate(double dt) {
    if (!gf_trans_active) return;
    gf_trans_elapsed += dt;
    if (gf_trans_elapsed >= gf_trans_duration) {
        gf_trans_elapsed = gf_trans_duration;
        gf_trans_active = 0;
    }
}

double tsuchi_gf_transitionAlpha(void) {
    if (gf_trans_duration <= 0) return 0;
    double t = gf_trans_elapsed / gf_trans_duration;
    if (t > 1.0) t = 1.0;
    /* Fade out then fade in: 0→255→0 */
    if (t < 0.5) return t * 2.0 * 255.0;
    return (1.0 - (t - 0.5) * 2.0) * 255.0;
}

int tsuchi_gf_transitionDone(void) { return !gf_trans_active; }
double tsuchi_gf_transitionNextScene(void) { return gf_trans_next_scene; }

/* ═══════════════════════════════════════════
 * Section 10: Physics Helpers
 * ═══════════════════════════════════════════ */

double tsuchi_gf_physGravity(double vy, double g, double dt) {
    return vy + g * dt;
}

double tsuchi_gf_physFriction(double v, double friction, double dt) {
    if (v > 0) {
        v -= friction * dt;
        if (v < 0) v = 0;
    } else if (v < 0) {
        v += friction * dt;
        if (v > 0) v = 0;
    }
    return v;
}

double tsuchi_gf_physClamp(double val, double min_val, double max_val) {
    if (val < min_val) return min_val;
    if (val > max_val) return max_val;
    return val;
}

/* ═══════════════════════════════════════════
 * Section 11: Particle System
 * ═══════════════════════════════════════════ */

#define GF_MAX_PARTICLES 256

typedef struct {
    double x, y, vx, vy;
    double life, maxLife;
    unsigned int color;
    int active;
} GfParticle;

static GfParticle gf_particles[GF_MAX_PARTICLES];

void tsuchi_gf_particleEmit(double x, double y, double vx, double vy,
                            double life, double color) {
    for (int i = 0; i < GF_MAX_PARTICLES; i++) {
        if (!gf_particles[i].active) {
            gf_particles[i].x = x;
            gf_particles[i].y = y;
            gf_particles[i].vx = vx;
            gf_particles[i].vy = vy;
            gf_particles[i].life = life;
            gf_particles[i].maxLife = life;
            gf_particles[i].color = (unsigned int)color;
            gf_particles[i].active = 1;
            return;
        }
    }
}

void tsuchi_gf_particleUpdate(double dt, double gravity) {
    for (int i = 0; i < GF_MAX_PARTICLES; i++) {
        if (!gf_particles[i].active) continue;
        gf_particles[i].vy += gravity * dt;
        gf_particles[i].x += gf_particles[i].vx * dt;
        gf_particles[i].y += gf_particles[i].vy * dt;
        gf_particles[i].life -= dt;
        if (gf_particles[i].life <= 0) {
            gf_particles[i].active = 0;
        }
    }
}

void tsuchi_gf_particleDraw(double size) {
    int sz = (int)size;
    for (int i = 0; i < GF_MAX_PARTICLES; i++) {
        if (!gf_particles[i].active) continue;
        Color c = gf_unpack_color((double)gf_particles[i].color);
        /* Fade alpha based on remaining life */
        double ratio = gf_particles[i].life / gf_particles[i].maxLife;
        if (ratio < 0) ratio = 0;
        c.a = (unsigned char)(ratio * 255);
        DrawRectangle((int)gf_particles[i].x, (int)gf_particles[i].y, sz, sz, c);
    }
}

double tsuchi_gf_particleCount(void) {
    int count = 0;
    for (int i = 0; i < GF_MAX_PARTICLES; i++) {
        if (gf_particles[i].active) count++;
    }
    return (double)count;
}

void tsuchi_gf_particleClear(void) {
    memset(gf_particles, 0, sizeof(gf_particles));
}

/* ═══════════════════════════════════════════
 * Section 12: Grid / Tilemap Utilities
 * ═══════════════════════════════════════════ */

double tsuchi_gf_gridToPx(double grid, double tileSize) {
    return grid * tileSize;
}

double tsuchi_gf_pxToGrid(double px, double tileSize) {
    if (tileSize <= 0) return 0;
    return floor(px / tileSize);
}

double tsuchi_gf_gridIndex(double x, double y, double cols) {
    return y * cols + x;
}

int tsuchi_gf_gridInBounds(double x, double y, double cols, double rows) {
    return x >= 0 && y >= 0 && x < cols && y < rows;
}

double tsuchi_gf_manhattan(double x1, double y1, double x2, double y2) {
    return fabs(x2 - x1) + fabs(y2 - y1);
}

double tsuchi_gf_chebyshev(double x1, double y1, double x2, double y2) {
    double dx = fabs(x2 - x1);
    double dy = fabs(y2 - y1);
    return dx > dy ? dx : dy;
}

/* ═══════════════════════════════════════════
 * Section 13: FSM (Finite State Machine)
 * ═══════════════════════════════════════════ */

#define GF_MAX_FSMS 8

typedef struct {
    int current;
    int prev;
    int frames;
} GfFSM;

static GfFSM gf_fsms[GF_MAX_FSMS];

void tsuchi_gf_fsmInit(double id, double state) {
    int i = (int)id;
    if (i < 0 || i >= GF_MAX_FSMS) return;
    gf_fsms[i].current = (int)state;
    gf_fsms[i].prev = (int)state;
    gf_fsms[i].frames = 0;
}

void tsuchi_gf_fsmSet(double id, double state) {
    int i = (int)id;
    if (i < 0 || i >= GF_MAX_FSMS) return;
    if (gf_fsms[i].current != (int)state) {
        gf_fsms[i].prev = gf_fsms[i].current;
        gf_fsms[i].current = (int)state;
        gf_fsms[i].frames = 0;
    }
}

void tsuchi_gf_fsmTick(double id) {
    int i = (int)id;
    if (i < 0 || i >= GF_MAX_FSMS) return;
    gf_fsms[i].frames++;
}

double tsuchi_gf_fsmState(double id) {
    int i = (int)id;
    if (i < 0 || i >= GF_MAX_FSMS) return 0;
    return (double)gf_fsms[i].current;
}

double tsuchi_gf_fsmPrev(double id) {
    int i = (int)id;
    if (i < 0 || i >= GF_MAX_FSMS) return 0;
    return (double)gf_fsms[i].prev;
}

double tsuchi_gf_fsmFrames(double id) {
    int i = (int)id;
    if (i < 0 || i >= GF_MAX_FSMS) return 0;
    return (double)gf_fsms[i].frames;
}

int tsuchi_gf_fsmJustEntered(double id) {
    int i = (int)id;
    if (i < 0 || i >= GF_MAX_FSMS) return 0;
    return gf_fsms[i].frames == 0;
}

/* ═══════════════════════════════════════════
 * Section 14: Object Pool
 * ═══════════════════════════════════════════ */

#define GF_MAX_POOLS 8
#define GF_POOL_SIZE 256

static int gf_pool_active[GF_MAX_POOLS][GF_POOL_SIZE];

double tsuchi_gf_poolAlloc(double poolId) {
    int p = (int)poolId;
    if (p < 0 || p >= GF_MAX_POOLS) return -1;
    for (int i = 0; i < GF_POOL_SIZE; i++) {
        if (!gf_pool_active[p][i]) {
            gf_pool_active[p][i] = 1;
            return (double)i;
        }
    }
    return -1;
}

void tsuchi_gf_poolFree(double poolId, double index) {
    int p = (int)poolId;
    int i = (int)index;
    if (p < 0 || p >= GF_MAX_POOLS) return;
    if (i < 0 || i >= GF_POOL_SIZE) return;
    gf_pool_active[p][i] = 0;
}

int tsuchi_gf_poolActive(double poolId, double index) {
    int p = (int)poolId;
    int i = (int)index;
    if (p < 0 || p >= GF_MAX_POOLS) return 0;
    if (i < 0 || i >= GF_POOL_SIZE) return 0;
    return gf_pool_active[p][i];
}

double tsuchi_gf_poolCount(double poolId) {
    int p = (int)poolId;
    if (p < 0 || p >= GF_MAX_POOLS) return 0;
    int count = 0;
    for (int i = 0; i < GF_POOL_SIZE; i++) {
        if (gf_pool_active[p][i]) count++;
    }
    return (double)count;
}

void tsuchi_gf_poolClear(double poolId) {
    int p = (int)poolId;
    if (p < 0 || p >= GF_MAX_POOLS) return;
    memset(gf_pool_active[p], 0, sizeof(gf_pool_active[p]));
}
