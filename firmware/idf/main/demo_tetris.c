// main/demo_tetris.c —— 俄罗斯方块小游戏（240x320 屏 + 三按键）
// 按键：UP=旋转(长按=暂停) DOWN=左移(长按=直落) OK=右移
// 渲染：单 canvas 重绘（避免 200 个对象的内存开销）
#include "demo.h"
#include "bsp_display.h"
#include "bsp_button.h"
#include "lvgl.h"
#include "esp_random.h"
#include "esp_log.h"
#include "esp_system.h"
#include <stdlib.h>
#include <string.h>

#define T_W 10
#define T_H 20
#define CELL 12
#define OX 12
#define OY 60

LV_FONT_DECLARE(lv_font_cn14);

static lv_obj_t *s_scr, *s_canvas, *s_score_lbl, *s_state_lbl;
static lv_timer_t *s_timer;
static uint8_t s_grid[T_H][T_W];
static int s_score, s_lines, s_level;
static bool s_running, s_over, s_paused;

typedef struct { int8_t x, y; } Pt;
static const Pt SHAPES[7][4] = {
    {{0,0},{1,0},{2,0},{3,0}},
    {{0,0},{1,0},{0,1},{1,1}},
    {{0,0},{1,0},{2,0},{1,1}},
    {{0,0},{1,0},{2,0},{2,1}},
    {{0,0},{1,0},{2,0},{0,1}},
    {{0,1},{1,1},{1,0},{2,0}},
    {{0,0},{1,0},{1,1},{2,1}},
};
static const uint32_t COLORS[8] = {0, 0x00CED1, 0xFFD700, 0x9370DB, 0xFF8C00, 0x4169E1, 0x2ECC71, 0xE74C3C};

static Pt s_cur[4];
static int s_cx, s_cy, s_type;

static void draw_cell_px(lv_obj_t *cv, int x, int y, uint32_t color) {
    // 直接操作 canvas buffer（ARGB8888? C3 用 RGB565）——用 lv_canvas_set_px
    lv_color_t c = lv_color_hex(color);
    for (int dy = 0; dy < CELL - 1; dy++)
        for (int dx = 0; dx < CELL - 1; dx++)
            lv_canvas_set_px(cv, x + dx, y + dy, c, LV_OPA_COVER);
}

static void draw(void) {
    if (!s_canvas) return;
    // 清背景
    lv_color_t bg = lv_color_hex(0x222222);
    for (int y = 0; y < T_H * CELL; y++)
        for (int x = 0; x < T_W * CELL; x++)
            lv_canvas_set_px(s_canvas, x, y, bg, LV_OPA_COVER);

    for (int yy = 0; yy < T_H; yy++)
        for (int xx = 0; xx < T_W; xx++)
            if (s_grid[yy][xx]) {
                int px = xx * CELL + 1, py = yy * CELL + 1;
                for (int dy = 0; dy < CELL - 2; dy++)
                    for (int dx = 0; dx < CELL - 2; dx++)
                        lv_canvas_set_px(s_canvas, px + dx, py + dy, lv_color_hex(COLORS[s_grid[yy][xx]]), LV_OPA_COVER);
            }
    // 当前方块
    if (!s_over) {
        for (int i = 0; i < 4; i++) {
            int gx = s_cx + s_cur[i].x, gy = s_cy + s_cur[i].y;
            if (gy >= 0 && gy < T_H && gx >= 0 && gx < T_W) {
                int px = gx * CELL + 1, py = gy * CELL + 1;
                for (int dy = 0; dy < CELL - 2; dy++)
                    for (int dx = 0; dx < CELL - 2; dx++)
                        lv_canvas_set_px(s_canvas, px + dx, py + dy, lv_color_hex(COLORS[s_type + 1]), LV_OPA_COVER);
            }
        }
    }

    if (s_over) {
        lv_label_set_text(s_state_lbl, "游戏结束！\n按 OK 重新开始");
        lv_obj_clear_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);
    } else if (s_paused) {
        lv_label_set_text(s_state_lbl, "暂停中\n长按上键继续");
        lv_obj_clear_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);
    }
}

static bool collide(int nx, int ny, Pt *buf) {
    for (int i = 0; i < 4; i++) {
        int x = buf ? buf[i].x : s_cur[i].x;
        int y = buf ? buf[i].y : s_cur[i].y;
        int gx = nx + x, gy = ny + y;
        if (gx < 0 || gx >= T_W || gy >= T_H) return true;
        if (gy >= 0 && s_grid[gy][gx]) return true;
    }
    return false;
}

static void rotate(void) {
    Pt r[4];
    for (int i = 0; i < 4; i++) {
        int8_t x = s_cur[i].x, y = s_cur[i].y;
        // 3x3 旋转
        r[i].x = 2 - y;
        r[i].y = x;
        // I 形(4宽) 平移修正
    }
    if (!collide(s_cx, s_cy, r)) memcpy(s_cur, r, sizeof(r));
}

static void merge(void) {
    for (int i = 0; i < 4; i++) {
        int gx = s_cx + s_cur[i].x, gy = s_cy + s_cur[i].y;
        if (gy >= 0 && gy < T_H && gx >= 0 && gx < T_W)
            s_grid[gy][gx] = s_type + 1;
    }
}

static void clear_lines(void) {
    int cleared = 0;
    for (int y = T_H - 1; y >= 0; y--) {
        bool full = true;
        for (int x = 0; x < T_W; x++) if (!s_grid[y][x]) { full = false; break; }
        if (full) {
            cleared++;
            for (int yy = y; yy > 0; yy--) memcpy(s_grid[yy], s_grid[yy-1], T_W);
            memset(s_grid[0], 0, T_W);
            y++;
        }
    }
    if (cleared) {
        s_lines += cleared;
        s_score += (cleared == 1 ? 100 : cleared == 2 ? 300 : cleared == 3 ? 500 : 800) * (s_level + 1);
        s_level = s_lines / 10;
        lv_label_set_text_fmt(s_score_lbl, "分数 %d\n行数 %d 关 %d", s_score, s_lines, s_level);
    }
}

static void spawn(void) {
    s_type = esp_random() % 7;
    for (int i = 0; i < 4; i++) s_cur[i] = SHAPES[s_type][i];
    s_cx = 3; s_cy = 0;
    if (collide(s_cx, s_cy, NULL)) s_over = true;
}

static void step(void) {
    if (!s_running || s_over || s_paused) return;
    if (!collide(s_cx, s_cy + 1, NULL)) {
        s_cy++;
    } else {
        merge();
        clear_lines();
        if (!s_over) spawn();
    }
    draw();
}

static void timer_cb(lv_timer_t *t) {
    (void)t;
    static int cnt = 0;
    int speed = 5 - s_level; if (speed < 1) speed = 1;
    if (++cnt >= speed) { cnt = 0; step(); }
}

static void reset_game(void) {
    memset(s_grid, 0, sizeof(s_grid));
    s_score = s_lines = s_level = 0;
    s_over = s_paused = false;
    s_running = true;
    lv_label_set_text_fmt(s_score_lbl, "分数 0\n行数 0 关 0");
    spawn();
    draw();
}

#define CB_W (T_W * CELL)
#define CB_H (T_H * CELL)
static lv_color_t s_cbuf[CB_W * CB_H];

static const char *TAG_T = "tetris";
void demo_tetris_enter(void) {
    ESP_LOGI(TAG_T, "enter: creating screen");
    s_scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_scr, lv_color_hex(0x101018), 0);
    lv_obj_remove_flag(s_scr, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *title = lv_label_create(s_scr);
    lv_label_set_text(title, "俄罗斯方块");
    lv_obj_set_style_text_font(title, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(0xFFFFFF), 0);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 6);

    s_score_lbl = lv_label_create(s_scr);
    lv_obj_set_style_text_font(s_score_lbl, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_score_lbl, lv_color_hex(0x88FF88), 0);
    lv_obj_align(s_score_lbl, LV_ALIGN_TOP_RIGHT, -8, 26);

    ESP_LOGI(TAG_T, "creating canvas");
    s_canvas = lv_canvas_create(s_scr);
    lv_canvas_set_buffer(s_canvas, s_cbuf, CB_W, CB_H, LV_COLOR_FORMAT_NATIVE);
    lv_obj_set_pos(s_canvas, OX, OY);

    lv_obj_t *help = lv_label_create(s_scr);
    lv_obj_set_style_text_font(help, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(help, lv_color_hex(0xAAAAAA), 0);
    lv_obj_set_pos(help, OX + T_W * CELL + 8, OY + 8);
    lv_label_set_text(help, "上键 旋转\n下键 左移\nOK 右移\n长按下\n直落");

    s_state_lbl = lv_label_create(s_scr);
    lv_obj_set_style_text_font(s_state_lbl, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_state_lbl, lv_color_hex(0xFFFF00), 0);
    lv_obj_align(s_state_lbl, LV_ALIGN_CENTER, 0, 0);
    lv_obj_add_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);

    ESP_LOGI(TAG_T, "canvas buf set");
    reset_game();
    ESP_LOGI(TAG_T, "reset done, free heap=%u", (unsigned)esp_get_free_heap_size());
    s_timer = lv_timer_create(timer_cb, 120, NULL);
    lv_screen_load(s_scr);
    ESP_LOGI(TAG_T, "enter complete");
}

void demo_tetris_exit(void) {
    if (s_timer) { lv_timer_delete(s_timer); s_timer = NULL; }
    if (s_scr) { lv_obj_delete(s_scr); s_scr = NULL; }
    s_canvas = NULL;
    s_running = false;
}

void demo_tetris_key(bsp_btn_t btn, bsp_btn_ev_t ev) {
    if (s_over) {
        if (btn == BSP_BTN_OK && ev == BSP_BTN_CLICK) reset_game();
        return;
    }
    if (btn == BSP_BTN_UP && ev == BSP_BTN_CLICK) {
        if (!s_paused) { rotate(); draw(); }
    } else if (btn == BSP_BTN_UP && ev == BSP_BTN_LONG) {
        s_paused = !s_paused;
        draw();
    } else if (btn == BSP_BTN_DOWN && ev == BSP_BTN_CLICK) {
        if (!s_paused && !collide(s_cx - 1, s_cy, NULL)) { s_cx--; draw(); }
    } else if (btn == BSP_BTN_DOWN && ev == BSP_BTN_LONG) {
        if (!s_paused) {
            while (!collide(s_cx, s_cy + 1, NULL)) s_cy++;
            merge(); clear_lines(); if (!s_over) spawn(); draw();
        }
    } else if (btn == BSP_BTN_OK && ev == BSP_BTN_CLICK) {
        if (!s_paused && !collide(s_cx + 1, s_cy, NULL)) { s_cx++; draw(); }
    }
}
