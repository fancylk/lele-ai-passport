// main/demo_catch.c —— 左右接球(纯 LVGL 控件实现,零大块内存分配,零逐像素绘制)
// 球从顶部随机偏向左/右落下,玩家预测落点:下键=站左边,OK=站右边
// 接住+1 分,漏球-1 命(3 命),速度渐增
//
// 旧版用 lv_canvas + lv_malloc(150KB) 全屏缓冲:C3 无 PSRAM 分配常失败,
// NULL 缓冲渲染即崩;且每帧 7.6 万次 set_px 拖死 LVGL。改为控件移动后
// 仅 3 个小矩形重布局,内存与 CPU 开销可忽略。
#include "demo.h"
#include "bsp_display.h"
#include "bsp_button.h"
#include "lvgl.h"
#include "esp_random.h"
#include <stdio.h>

LV_FONT_DECLARE(lv_font_cn14);

#define CATCH_W 240
#define CATCH_H 320
#define BALL_SZ 14
#define PLAYER_W (CATCH_W / 2 - 8)   // 球拍几乎填满半区,仅留 4px 边距
#define PLAYER_H 10
#define PLAYER_Y (CATCH_H - 24)   // 玩家横条顶部 y

static lv_obj_t *s_scr, *s_hud, *s_state_lbl, *s_ball, *s_player;
static lv_timer_t *s_timer;
static bool s_running, s_over;
static int s_score, s_lives, s_speed;
static int s_ball_x, s_ball_y;    // 球心坐标
static int s_vx, s_vy;            // 速度分量
static int s_side;                // 0=左 1=右(玩家当前站位)

static void place_ball(void) {
    lv_obj_set_pos(s_ball, s_ball_x - BALL_SZ / 2, s_ball_y - BALL_SZ / 2);
}

static void place_player(void) {
    int px = (s_side == 0) ? 4 : (CATCH_W / 2 + 4);
    lv_obj_set_pos(s_player, px, PLAYER_Y);
}

static void update_hud(void) {
    lv_label_set_text_fmt(s_hud, "得分 %d    生命 %d", s_score, s_lives);
}

static void new_ball(void) {
    s_ball_x = BALL_SZ + (int)(esp_random() % (CATCH_W - 2 * BALL_SZ));
    s_ball_y = BALL_SZ + 24;
    s_vx = (esp_random() % 2) ? s_speed : -s_speed;
    s_vy = s_speed;
}

static void game_over(void) {
    s_over = true;
    char buf[64];
    snprintf(buf, sizeof(buf), "游戏结束！\n得分: %d\n按 OK 再来", s_score);
    lv_label_set_text(s_state_lbl, buf);
    lv_obj_remove_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);
}

static void catch_check(void) {
    if (s_ball_y + BALL_SZ / 2 < PLAYER_Y) return;
    // 球与当前半区球拍横向重叠即算接住(贴中线的球也不会误判)
    int px = (s_side == 0) ? 4 : (CATCH_W / 2 + 4);
    bool caught = (s_ball_x + BALL_SZ / 2 >= px) && (s_ball_x - BALL_SZ / 2 <= px + PLAYER_W);
    if (caught) {
        s_score++;
    } else if (--s_lives <= 0) {
        game_over();
        return;
    }
    update_hud();
    s_speed++;
    new_ball();
    place_ball();
}

static void timer_cb(lv_timer_t *t) {
    (void)t;
    if (!s_running || s_over) return;
    s_ball_x += s_vx;
    s_ball_y += s_vy;
    // 左右墙反弹
    if (s_ball_x < BALL_SZ / 2) { s_ball_x = BALL_SZ / 2; s_vx = -s_vx; }
    if (s_ball_x > CATCH_W - BALL_SZ / 2) { s_ball_x = CATCH_W - BALL_SZ / 2; s_vx = -s_vx; }
    catch_check();
    if (!s_over) place_ball();
}

static void reset_game(void) {
    s_score = 0;
    s_lives = 3;
    s_speed = 3;
    s_over = false;
    s_running = true;
    s_side = 0;
    place_player();
    update_hud();
    new_ball();
    place_ball();
    lv_obj_add_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);
}

// 通用小方块:无边框无内边距,位置尺寸即所见
static lv_obj_t *block_obj(lv_obj_t *parent, int x, int y, int w, int h, uint32_t color, int radius) {
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_pos(o, x, y);
    lv_obj_set_size(o, w, h);
    lv_obj_set_style_bg_color(o, lv_color_hex(color), 0);
    lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(o, 0, 0);
    lv_obj_set_style_pad_all(o, 0, 0);
    lv_obj_set_style_radius(o, radius, 0);
    return o;
}

void demo_catch_enter(void) {
    s_scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_scr, lv_color_hex(0x101018), 0);
    lv_obj_remove_flag(s_scr, LV_OBJ_FLAG_SCROLLABLE);

    s_hud = lv_label_create(s_scr);
    lv_obj_set_style_text_font(s_hud, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_hud, lv_color_hex(0x88FF88), 0);
    lv_obj_align(s_hud, LV_ALIGN_TOP_MID, 0, 6);

    // 中线(左右半区分界)
    block_obj(s_scr, CATCH_W / 2 - 1, 26, 2, CATCH_H - 26, 0x333344, 0);

    s_ball = block_obj(s_scr, 0, 0, BALL_SZ, BALL_SZ, 0xFFD700, LV_RADIUS_CIRCLE);
    s_player = block_obj(s_scr, 10, PLAYER_Y, PLAYER_W, PLAYER_H, 0x2ECC71, 3);

    s_state_lbl = lv_label_create(s_scr);
    lv_obj_set_style_text_font(s_state_lbl, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_state_lbl, lv_color_hex(0xFFFF00), 0);
    lv_obj_align(s_state_lbl, LV_ALIGN_CENTER, 0, 0);
    lv_obj_add_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);

    reset_game();
    // 等按键开始(与旧版交互一致)
    s_running = false;
    lv_label_set_text(s_state_lbl, "预测球落点！\n上键=站左  下键=站右\n按任意键开始");
    lv_obj_remove_flag(s_state_lbl, LV_OBJ_FLAG_HIDDEN);

    s_timer = lv_timer_create(timer_cb, 40, NULL);
    lv_screen_load(s_scr);
}

void demo_catch_exit(void) {
    if (s_timer) { lv_timer_delete(s_timer); s_timer = NULL; }
    if (s_scr) { lv_obj_delete(s_scr); s_scr = NULL; }
    s_ball = s_player = s_hud = s_state_lbl = NULL;
    s_running = false;
}

void demo_catch_key(bsp_btn_t btn, bsp_btn_ev_t ev) {
    if (ev != BSP_BTN_CLICK && ev != BSP_BTN_LONG) return;
    if (!s_running) {
        reset_game();   // 按任意键开始
        return;
    }
    if (s_over) {
        if (btn == BSP_BTN_OK) reset_game();
        return;
    }
    if (btn == BSP_BTN_UP) s_side = 0;        // 上=左
    else if (btn == BSP_BTN_DOWN) s_side = 1; // 下=右
    else return;
    place_player();
}
