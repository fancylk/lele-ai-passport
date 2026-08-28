// main/demo_answer.c —— 答案之书:心中默想一个问题,按任意键翻开一页神秘答案。
// 纯离线小应用:星空夜色主题,40 条儿童友好签文,连续两次不会翻到同一句。
#include "demo.h"
#include "bsp_display.h"
#include "bsp_button.h"
#include "ui_pixel.h"
#include "lvgl.h"
#include "esp_random.h"
#include <stdio.h>

LV_FONT_DECLARE(lv_font_cn14);

// 签文库(全部常用字,已逐字校验 lv_font_cn14 字形覆盖)
static const char *ANSWERS[] = {
    "是的", "不是", "当然", "当然不行", "毫无疑问",
    "毋庸置疑", "肯定", "绝对不", "对的", "错的",
    "没有问题", "这是一定的", "显而易见", "命中注定", "心诚则灵",
    "天机不可泄露", "时机未到", "马上行动", "你再等等看", "试试才知道",
    "大胆去做", "相信直觉", "听听心声", "保持乐观", "保持现状",
    "换个思路", "注意细节", "列个清单", "制定计划", "坚持下去",
    "去争取机会", "抓住机会", "机会稍纵即逝", "等待机会", "尽早完成",
    "很快就能解决", "需要点时间", "结果不错", "值得期待", "有好运",
    "它会带来好运", "天上要掉馅饼了", "意义非凡", "至关重要", "不太靠谱",
    "并不明智", "再考虑一下", "重新考虑", "形势不明", "谁说得准呢",
    "不可预测", "表示怀疑", "需要更多信息", "问天问地不如问自己", "你就是答案",
    "答案在镜子里", "默数十秒再问我", "一年后就不重要了", "玩得开心就好", "你开心就好",
    "一笑而过", "保持微笑", "不要害怕", "别想太多", "保持头脑清醒",
    "冷静一下", "深呼吸", "喝口水再说", "休息一会", "先睡一觉",
    "起来动一动", "去户外走走", "转移注意力", "发挥想象力", "保持好奇心",
    "去挖掘真相", "说出来吧", "大声说出来", "找人给点意见", "请教妈妈",
    "去问爸爸", "去问乐乐", "寻找指路人", "借助他人经验", "学会协作",
    "量力而行", "实际一点", "走容易走的路", "不走寻常路", "遵守规则",
    "克服困难", "扫除障碍", "勿忘初心", "但行好事莫问前程", "改变不了世界就改变自己",
    "主动一点", "你需要主动", "不要犹豫", "不要等了", "决定了就去做",
    "去尝试", "去做", "GO", "采取行动", "继续前进",
    "着眼未来", "观察形势", "观望", "要有耐心", "需要等待",
    "等待更好的", "情况很快会变化", "事情开始有趣了", "有意料之外的好事", "看看会发生什么",
    "记录下来", "保存实力", "学会妥协", "值得一试", "不值得冒险",
    "谨慎小心", "注意安全", "少吃点零食", "别做梦了", "荒谬",
    "需要一点帮助", "你不会失望的", "也许会失望", "取决于你的选择", "能让你快乐的那个决定",
    "怎么选结果都不坏", "相信最初的想法", "想法太多选择太少", "寻找更多选择", "还有另一种可能",
    "没有更好的选择", "抛开首选方案", "制订一个新计划", "关注身边的人", "对他人慷慨",
    "帮助别人", "说声谢谢", "给个拥抱", "交个新朋友", "别让情绪左右你",
    "不要过火", "输了也没关系", "输了再来一局", "赢是迟早的事", "去读一本书",
    "画一幅画", "唱首歌吧", "去数星星", "看看云像什么", "听听风的声音",
    "答案在风中", "星星说可以", "月亮说不行", "太阳说加油", "彩虹在等你",
    "恐龙都不知道", "问导游乐乐", "去旅行吧", "下一站更好", "地图会告诉你",
    "先吃点好的", "来根冰激凌", "多喝水", "收拾下书包", "先做完作业",
    "十分钟后再说", "明天再说", "一定会如愿的", "会如愿的", "冲就完事",
    "一定行", "必须的呀", "有点悬", "概率很大", "概率很小",
    "五五开", "试试卖萌", "保持沉默", "静观其变", "去踢足球",
    "去跳绳", "给花浇浇水", "写三行日记", "背首诗试试", "去问老师",
    "折个纸飞机", "吹个泡泡", "捡一片树叶", "把秘密写下来", "数到十再决定",
    "先迈左脚", "掷个硬币吧", "剪刀石头布", "和爸爸下盘棋", "拼图去",
};
#define ANSWER_N 200  // 签文总数(参考:Carol Bolt 原版约 200 条/koishi 插件 209 条)
#define ANSWER_N (sizeof(ANSWERS) / sizeof(ANSWERS[0]))

// 夜色神秘主题配色
#define AB_BG     0x14102A
#define AB_PANEL  0x241A4A
#define AB_GOLD   0xFFD928
#define AB_MUTED  0x9C93C9

static lv_obj_t *s_scr, *s_page_lbl, *s_hint_lbl;
static lv_timer_t *s_reveal_timer;
static int s_last = -1;

// 600ms 悬念后揭晓(运行在 LVGL 任务定时器里,无需加锁)
static void reveal_cb(lv_timer_t *t) {
    (void)t;
    s_reveal_timer = NULL;
    if (!s_page_lbl) return;
    int i;
    do { i = (int)(esp_random() % ANSWER_N); } while ((int)ANSWER_N > 1 && i == s_last);
    s_last = i;
    lv_label_set_text_fmt(s_page_lbl, "「%s」", ANSWERS[i]);
}

// 连按忽略:等当前这一页翻开后再说
static void show_pending(void) {
    if (s_reveal_timer) return;
    if (s_page_lbl) lv_label_set_text(s_page_lbl, "天机推演中...");
    s_reveal_timer = lv_timer_create(reveal_cb, 600, NULL);
    lv_timer_set_repeat_count(s_reveal_timer, 1);
}

void demo_answer_enter(void) {
    s_scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_scr, lv_color_hex(AB_BG), 0);
    lv_obj_remove_flag(s_scr, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *title = ui_pixel_label(s_scr, "答案之书", &lv_font_cn14, AB_GOLD);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 16);

    // 书页面板:星紫底 + 金边(ui_pixel_panel 自带 INK 投影,换金边呼应夜色)
    lv_obj_t *book = ui_pixel_panel_create(s_scr, 30, 80, 180, 140, AB_PANEL);
    lv_obj_set_style_border_color(book, lv_color_hex(AB_GOLD), 0);

    s_page_lbl = lv_label_create(book);
    lv_obj_set_style_text_font(s_page_lbl, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_page_lbl, lv_color_hex(AB_GOLD), 0);
    lv_label_set_text(s_page_lbl, "默想你的问题");
    lv_obj_center(s_page_lbl);

    s_hint_lbl = ui_pixel_label(s_scr, "心诚则灵 按任意键翻开", &lv_font_cn14, AB_MUTED);
    lv_obj_align(s_hint_lbl, LV_ALIGN_BOTTOM_MID, 0, -18);

    s_reveal_timer = NULL;
    lv_screen_load(s_scr);
}

void demo_answer_exit(void) {
    if (s_reveal_timer) { lv_timer_delete(s_reveal_timer); s_reveal_timer = NULL; }
    if (s_scr) { lv_obj_delete(s_scr); s_scr = NULL; }
    s_page_lbl = s_hint_lbl = NULL;
}

void demo_answer_key(bsp_btn_t btn, bsp_btn_ev_t ev) {
    (void)btn;
    if (ev != BSP_BTN_CLICK) return;    // 长按 OK 返回菜单已由 main.c 统一拦截
    show_pending();
}
