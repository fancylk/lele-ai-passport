// main/demo_catch.c —— 左右接球（简化打砖块反应游戏）
// 球从顶部随机偏向左/右落下，玩家预测落点：下键=站左边，OK=站右边
// 接住+1 分，漏球-1 命（3 命），速度渐增
#include "demo.h"
#include "bsp_display.h"
#include "bsp_button.h"
#include "lvgl.h"
#include "esp_random.h"
#include "esp_log.h"
#include <stdio.h>

LV_FONT_DECLARE(lv_font_cn14);

#define CATCH_W 240
#define CATCH_H 320
#define BALL_R 6
#define PLAYER_W 60
#define PLAYER_H 10

static lv_obj_t *s_scr, *s_canvas, *s_hud, *s_state_lbl;
static lv_timer_t *s_timer;
static lv_color_t *s_cbuf;
static bool s_running, s_over;
static bool s_paused_unused = false;
static int s_score, s_lives, s_speed;
static int s_ball_x, s_ball_y;      // 球心坐标
static int s_vx, s_vy;              // 速度分量
static int s_player_x;              // 玩家（底部横条）左端
static int s_side;                  // 0=左 1=右（玩家当前站位）
static const char *TAG_C = "catch";

static lv_color_t bg_c, line_c, ball_c, player_c;

static void draw_frame(void) {
    // 清屏
    for (int y = 0; y < CATCH_H; y++)
        for (int x = 0; x < CATCH_W; x++)
            lv_canvas_set_px(s_canvas, x, y, bg_c, LV_OPA_COVER);
    // 中线（左右分界）
    for (int y = 0; y < CATCH_H; y++)
        lv_canvas_set_px(s_canvas, CATCH_W/2, y, line_c, LV_OPA_COVER);
    // 球
    for (int dy = -BALL_R; dy <= BALL_R; dy++)
        for (int dx = -BALL_R; dx <= BALL_R; dx++)
            if (dx*dx + dy*dy <= BALL_R*BALL_R) {
                int px = s_ball_x + dx, py = s_ball_y + dy;
                if (px >= 0 && px < CATCH_W && py >= 0 && py < CATCH_H)
                    lv_canvas_set_px(s_canvas, px, py, ball_c, LV_OPA_COVER);
            }
    // 玩家横条
    for (int dy = 0; dy < PLAYER_H; dy++)
        for (int dx = 0; dx < PLAYER_W; dx++) {
            int px = s_player_x + dx, py = CATCH_H - 24 + dy;
            if (px >= 0 && px < CATCH_W)
                lv_canvas_set_px(s_canvas, px, py, player_c, LV_OPA_COVER);
        }
    // 分隔线加粗提示玩家半区
    (void)s_side;
}

static void update_hud(void) {
    lv_label_set_text_fmt(s_hud, "得分 %d    生命 %d", s_score, s_lives);
}

static void new_ball(void) {
    s_ball_x = BALL_R + esp_random() % (CATCH_W - 2*BALL_R);
    s_ball_y = BALL_R + 20;
    // 随机左右倾向
    s_vx = (esp_random() % 2) ? s_speed : -s_speed;
    s_vy = s_speed;
}

static void game_over(void) {
    s_over = true;
    char buf[64];
    snprintf(buf, sizeof(buf), "游戏结束！\n得分: %d\n按 OK 再来", s_score);
    lv_label_set_text(s_state_lbl, buf);
    lv_obj_clear_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);
}

static void catch_check(void) {
    // 球到底部区域：判定玩家横条位置
    if (s_ball_y + BALL_R >= CATCH_H - 24) {
        int ball_side = (s_ball_x < CATCH_W/2) ? 0 : 1;
        if (ball_side == s_side) {
            s_score++;
        } else {
            s_lives--;
            if (s_lives <= 0) { draw_frame(); game_over(); return; }
        }
        update_hud();
        s_speed++;
        new_ball();
    }
}

static void timer_cb(lv_timer_t *t) {
    (void)t;
    if (!s_running || s_over) return;
    s_ball_x += s_vx; s_ball_y += s_vy;
    // 左右墙反弹
    if (s_ball_x < BALL_R) { s_ball_x = BALL_R; s_vx = -s_vx; }
    if (s_ball_x > CATCH_W - BALL_R) { s_ball_x = CATCH_W - BALL_R; s_vx = -s_vx; }
    catch_check();
    // 玩家条位置跟随站位
    s_player_x = (s_side == 0) ? 10 : (CATCH_W - PLAYER_W - 10);
    draw_frame();
}

static void reset_game(void) {
    s_score = 0; s_lives = 3; s_speed = 3;
    s_over = s_paused_unused = false;
    s_running = true;
    s_side = 0;
    s_player_x = 10;
    update_hud();
    new_ball();
}

void demo_catch_enter(void) {
    s_scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_scr, lv_color_hex(0x101018), 0);
    lv_obj_remove_flag(s_scr, LV_OBJ_FLAG_SCROLLABLE);

    s_hud = lv_label_create(s_scr);
    lv_obj_set_style_text_font(s_hud, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_hud, lv_color_hex(0x88FF88), 0);
    lv_obj_align(s_hud, LV_ALIGN_TOP_MID, 0, 6);

    s_canvas = lv_canvas_create(s_scr);
    s_cbuf = lv_malloc(CATCH_W * CATCH_H * sizeof(lv_color_t));
    lv_canvas_set_buffer(s_canvas, s_cbuf, CATCH_W, CATCH_H, LV_COLOR_FORMAT_NATIVE);
    lv_obj_set_pos(s_canvas, 0, 0);

    s_state_lbl = lv_label_create(s_scr);
    lv_obj_set_style_text_font(s_state_lbl, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_state_lbl, lv_color_hex(0xFFFF00), 0);
    lv_obj_align(s_state_lbl, LV_ALIGN_CENTER, 0, 0);
    lv_obj_add_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);

    bg_c = lv_color_hex(0x101018);
    line_c = lv_color_hex(0x333344);
    ball_c = lv_color_hex(0xFFD700);
    player_c = lv_color_hex(0x2ECC71);

    reset_game();
    lv_label_set_text(s_state_lbl, "预测球落点！\n下键=站左  OK=站右\n按任意键开始");
    lv_obj_clear_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);
    s_running = false;  // 等按键开始

    s_timer = lv_timer_create(timer_cb, 40, NULL);
    lv_screen_load(s_scr);
}

void demo_catch_exit(void) {
    if (s_timer) { lv_timer_delete(s_timer); s_timer = NULL; }
    if (s_cbuf) { lv_free(s_cbuf); s_cbuf = NULL; }
    if (s_scr) { lv_obj_delete(s_scr); s_scr = NULL; }
    s_canvas = NULL;
    s_running = false;
}

void demo_catch_key(bsp_btn_t btn, bsp_btn_ev_t ev) {
    if (ev != BSP_BTN_CLICK && ev != BSP_BTN_LONG) return;
    if (!s_running) {
        // 开始游戏
        reset_game();
        return;
    }
    if (s_over) {
        if (btn == BSP_BTN_OK) reset_game();
        return;
    }
    if (btn == BSP_BTN_DOWN) s_side = 0;
    else if (btn == BSP_BTN_OK) s_side = 1;
    else return;
    s_player_x = (s_side == 0) ? 10 : (CATCH_W - PLAYER_W - 10);
    draw_frame();
}
