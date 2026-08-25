// main/app_lele_guide.c —— 乐乐 AI 导游工牌原生全流程应用
#include "demo.h"
#include "bsp_audio.h"
#include "bsp_display.h"
#include "bsp_button.h"
#include "bsp_battery.h"
#include "ui_pixel.h"
#include "lvgl.h"

#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "cJSON.h"

static const char *TAG = "lele_guide";

#define WIFI_SSID       "CMCC-Ab9h"
#define WIFI_PASS       "tvakk9k8"
#define BRIDGE_IP       "124.221.187.167"
#define UDP_PORT        8888

#define SAMPLE_RATE     16000
#define CHUNK_SAMPLES   512
#define MAX_REC_SEC     4

typedef enum {
    STATE_GUIDE = 0,
    STATE_LISTENING,
    STATE_PROCESSING,
    STATE_PROPOSAL,
    STATE_DEPLOYING,
    STATE_SUCCESS
} app_state_t;

static app_state_t s_state = STATE_GUIDE;
static lv_obj_t *s_scr = NULL;
static lv_obj_t *s_lbl_title = NULL;
static lv_obj_t *s_lbl_sub = NULL;
static lv_obj_t *s_lbl_poem = NULL;
static lv_obj_t *s_lbl_desc = NULL;
static lv_obj_t *s_lbl_action = NULL;
static lv_obj_t *s_mascot = NULL;

static int s_spot_idx = 0;
static int s_udp_sock = -1;
static struct sockaddr_in s_dest_addr;
static bool s_wifi_connected = false;

typedef struct {
    const char *spot;
    const char *city;
    const char *grade;
    const char *poem;
    const char *verse;
    const char *quiz;
} spot_info_t;

static const spot_info_t SPOTS[] = {
    {"白马寺", "洛阳", "历史典故", "《题白马寺》· 贾岛", "白马驮经自宛延，空门从此度人天。", "白马驮经四字口诀！"},
    {"龙门石窟", "洛阳", "七年级下册", "《春夜洛城闻笛》· 李白", "谁家玉笛暗飞声，散入春风满洛城。", "东方蒙娜丽莎大佛微笑！"},
    {"夫子庙", "南京", "四年级必背", "《乌衣巷》· 刘禹锡", "旧时王谢堂前燕，飞入寻常百姓家。", "王导谢安燕子入百姓家！"},
    {"中华门瓮城", "南京", "初中拓展", "《桂枝香》· 王安石", "千里澄江似练，翠峰如簇。", "关门捉贼瓮中捉鳖！"},
    {"大雁塔", "西安", "小学必背", "《登科后》· 孟郊", "春风得意马蹄疾，一日看尽长安花。", "玄奘西行17年建大雁塔！"},
    {"大唐不夜城", "西安", "名篇必背", "《将进酒》· 李白", "人生得意须尽欢，莫使金樽空对月。", "和李白对诗赢毛笔酥！"},
    {"秦始皇兵马俑", "西安", "初中古典", "《秦王扫六合》· 李白", "秦王扫六合，虎视何雄哉！", "地下八千勇士千人千面！"},
    {"华山西峰", "华山", "一年级必背", "《咏华山》· 寇准", "举头红日近，回首白云低。", "沉香劈山救母神石传说！"},
    {"函谷关", "三门峡", "八年级必背", "《潼关怀古》· 张养浩", "峰峦如聚，波涛如怒，山河表里潼关路。", "老子骑青牛紫气东来！"},
    {"清明上河园", "开封", "五年级必背", "《题临安邸》· 林升", "暖风熏得游人醉，直把杭州作汴州。", "自驾开封实现古诗同款！"},
    {"鼓楼夜市", "开封", "饮食文化", "《东京梦华录》", "夜市直至三更尽，才五更又复开张。", "四步吃灌汤包秘籍！"},
    {"龙亭公园", "开封", "五年级必背", "《示儿》· 陆游", "王师北定中原日，家祭无忘告乃翁。", "潘杨二湖湖水辨忠奸！"}
};
#define SPOTS_COUNT (sizeof(SPOTS) / sizeof(SPOTS[0]))

static char s_user_text[128] = "我想在开封夜市吃灌汤包看表演";
static char s_prop_title[128] = "开封鼓楼夜市 · 灌汤包与宋代市集";
static char s_prop_desc[256] = "教爸爸妈妈四步吃包口诀，探秘宋代市井百戏！";
static char s_prop_quiz[128] = "灌汤包的四步吃法口诀是什么？";

static int16_t *s_rec_buf = NULL;
static size_t s_rec_len = 0;
static TaskHandle_t s_rec_task = NULL;
static volatile bool s_recording = false;

static void update_guide_ui(void) {
    if (!bsp_lvgl_lock(500)) return;
    const spot_info_t *s = &SPOTS[s_spot_idx];
    
    char title_buf[64];
    snprintf(title_buf, sizeof(title_buf), "[%s] %s (%d/%d)", s->city, s->spot, s_spot_idx + 1, (int)SPOTS_COUNT);
    lv_label_set_text(s_lbl_title, title_buf);
    
    char sub_buf[64];
    snprintf(sub_buf, sizeof(sub_buf), "%s | %s", s->grade, s->poem);
    lv_label_set_text(s_lbl_sub, sub_buf);
    
    lv_label_set_text(s_lbl_poem, s->verse);
    
    char desc_buf[128];
    snprintf(desc_buf, sizeof(desc_buf), "💡 乐乐考考爸妈:\n%s", s->quiz);
    lv_label_set_text(s_lbl_desc, desc_buf);
    
    lv_label_set_text(s_lbl_action, "按住[上键]说话  [下键]翻页");
    bsp_lvgl_unlock();
}

static void show_listening_ui(void) {
    if (!bsp_lvgl_lock(500)) return;
    lv_label_set_text(s_lbl_title, "🎙️ 正在录制乐乐语音...");
    lv_label_set_text(s_lbl_sub, "请对着工牌麦克风说话");
    lv_label_set_text(s_lbl_poem, "正在采录 16kHz 高清音频...");
    lv_label_set_text(s_lbl_desc, "松开[上键]传送给大模型！");
    lv_label_set_text(s_lbl_action, "松开[上键]完成录音");
    bsp_lvgl_unlock();
}

static void show_proposal_ui(void) {
    if (!bsp_lvgl_lock(500)) return;
    char title_buf[256];
    snprintf(title_buf, sizeof(title_buf), "🤖 建议:%s", s_prop_title);
    lv_label_set_text(s_lbl_title, title_buf);
    
    char user_buf[384];
    snprintf(user_buf, sizeof(user_buf), "🗣️ 乐乐原话: \"%s\"", s_user_text);
    lv_label_set_text(s_lbl_sub, user_buf);
    
    lv_label_set_text(s_lbl_poem, s_prop_desc);
    
    char quiz_buf[256];
    snprintf(quiz_buf, sizeof(quiz_buf), "💡 考考爸妈:%s", s_prop_quiz);
    lv_label_set_text(s_lbl_desc, quiz_buf);
    
    lv_label_set_text(s_lbl_action, "[OK 确认提交]  [下键 取消]");
    bsp_lvgl_unlock();
}

static void show_success_ui(void) {
    if (!bsp_lvgl_lock(500)) return;
    lv_label_set_text(s_lbl_title, "🎉 任务已成功发布！");
    lv_label_set_text(s_lbl_sub, "快看 iPad 上的新内容！");
    lv_label_set_text(s_lbl_poem, "网页已自动同步刷新");
    lv_label_set_text(s_lbl_desc, "正在播放小米 MiMo 语音讲解...");
    lv_label_set_text(s_lbl_action, "太棒啦！");
    bsp_lvgl_unlock();
}

static void record_task_func(void *arg) {
    (void)arg;
    bsp_audio_set_format(SAMPLE_RATE, 16, 1);
    size_t max_samples = (size_t)SAMPLE_RATE * MAX_REC_SEC;
    
    if (!s_rec_buf) {
        s_rec_buf = malloc(max_samples * sizeof(int16_t));
    }
    if (!s_rec_buf) {
        ESP_LOGE(TAG, "Malloc failed for recording buffer");
        vTaskDelete(NULL);
        return;
    }

    s_rec_len = 0;
    ESP_LOGI(TAG, "Recording started...");
    
    while (s_recording && s_rec_len < max_samples) {
        size_t to_read = (max_samples - s_rec_len) < CHUNK_SAMPLES ? (max_samples - s_rec_len) : CHUNK_SAMPLES;
        if (bsp_audio_read(s_rec_buf + s_rec_len, to_read * sizeof(int16_t)) != ESP_OK) break;
        s_rec_len += to_read;
    }
    
    ESP_LOGI(TAG, "Recording finished, total %u samples (%u bytes)", (unsigned)s_rec_len, (unsigned)(s_rec_len * sizeof(int16_t)));
    
    if (s_udp_sock >= 0 && s_rec_len > 0) {
        char notify[128];
        snprintf(notify, sizeof(notify), "{\"type\":\"voice_audio_start\",\"samples\":%u}\n", (unsigned)s_rec_len);
        sendto(s_udp_sock, notify, strlen(notify), 0, (struct sockaddr *)&s_dest_addr, sizeof(s_dest_addr));
        
        uint8_t *raw = (uint8_t *)s_rec_buf;
        size_t total_bytes = s_rec_len * sizeof(int16_t);
        size_t sent = 0;
        while (sent < total_bytes) {
            size_t chunk = (total_bytes - sent) < 1024 ? (total_bytes - sent) : 1024;
            sendto(s_udp_sock, raw + sent, chunk, 0, (struct sockaddr *)&s_dest_addr, sizeof(s_dest_addr));
            sent += chunk;
            vTaskDelay(pdMS_TO_TICKS(5));
        }
        
        char end_notify[64] = "{\"type\":\"voice_audio_end\"}\n";
        sendto(s_udp_sock, end_notify, strlen(end_notify), 0, (struct sockaddr *)&s_dest_addr, sizeof(s_dest_addr));
        ESP_LOGI(TAG, "Audio PCM stream sent to N1 bridge successfully!");
    }
    
    s_rec_task = NULL;
    vTaskDelete(NULL);
}

static void udp_rx_task(void *arg) {
    (void)arg;
    char rx_buf[1024];
    while (1) {
        if (s_udp_sock >= 0) {
            int len = recv(s_udp_sock, rx_buf, sizeof(rx_buf) - 1, 0);
            if (len > 0) {
                rx_buf[len] = '\0';
                cJSON *root = cJSON_Parse(rx_buf);
                if (root) {
                    cJSON *type = cJSON_GetObjectItem(root, "type");
                    if (type && strcmp(type->valuestring, "proposal") == 0) {
                        cJSON *utext = cJSON_GetObjectItem(root, "user_text");
                        cJSON *title = cJSON_GetObjectItem(root, "title");
                        cJSON *desc = cJSON_GetObjectItem(root, "desc");
                        cJSON *quiz = cJSON_GetObjectItem(root, "quiz");
                        
                        if (utext) strncpy(s_user_text, utext->valuestring, sizeof(s_user_text) - 1);
                        if (title) strncpy(s_prop_title, title->valuestring, sizeof(s_prop_title) - 1);
                        if (desc) strncpy(s_prop_desc, desc->valuestring, sizeof(s_prop_desc) - 1);
                        if (quiz) strncpy(s_prop_quiz, quiz->valuestring, sizeof(s_prop_quiz) - 1);
                        
                        s_state = STATE_PROPOSAL;
                        show_proposal_ui();
                    } else if (type && strcmp(type->valuestring, "task_done") == 0) {
                        s_state = STATE_SUCCESS;
                        show_success_ui();
                        vTaskDelay(pdMS_TO_TICKS(2800));
                        s_state = STATE_GUIDE;
                        update_guide_ui();
                    }
                    cJSON_Delete(root);
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

static void wifi_event_handler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        s_wifi_connected = false;
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        s_wifi_connected = true;
        ESP_LOGI(TAG, "Wi-Fi connected! Setting up UDP socket...");
        
        s_udp_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
        s_dest_addr.sin_addr.s_addr = inet_addr(BRIDGE_IP);
        s_dest_addr.sin_family = AF_INET;
        s_dest_addr.sin_port = htons(UDP_PORT);
        
        struct sockaddr_in bind_addr;
        bind_addr.sin_addr.s_addr = htonl(INADDR_ANY);
        bind_addr.sin_family = AF_INET;
        bind_addr.sin_port = htons(UDP_PORT);
        bind(s_udp_sock, (struct sockaddr *)&bind_addr, sizeof(bind_addr));
        
        xTaskCreate(udp_rx_task, "udp_rx", 4096, NULL, 5, NULL);
    }
}

static void wifi_init_sta(void) {
    esp_netif_init();
    esp_event_loop_create_default();
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);

    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL);

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
    esp_wifi_start();
}

void demo_lele_guide_enter(void) {
    s_scr = ui_pixel_screen_create("LELE GUIDE");
    lv_obj_t *panel = ui_pixel_panel_create(s_scr, 10, 42, 220, 240, UI_PAPER);

    s_lbl_title = lv_label_create(panel);
    lv_obj_set_style_text_font(s_lbl_title, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(s_lbl_title, lv_color_hex(UI_INK), 0);
    lv_obj_set_width(s_lbl_title, 200);
    lv_obj_align(s_lbl_title, LV_ALIGN_TOP_LEFT, 6, 6);

    s_lbl_sub = lv_label_create(panel);
    lv_obj_set_style_text_color(s_lbl_sub, lv_color_hex(0x555555), 0);
    lv_obj_set_width(s_lbl_sub, 200);
    lv_obj_align(s_lbl_sub, LV_ALIGN_TOP_LEFT, 6, 32);

    s_lbl_poem = lv_label_create(panel);
    lv_obj_set_style_text_color(s_lbl_poem, lv_color_hex(UI_INK), 0);
    lv_obj_set_width(s_lbl_poem, 200);
    lv_label_set_long_mode(s_lbl_poem, LV_LABEL_LONG_WRAP);
    lv_obj_align(s_lbl_poem, LV_ALIGN_TOP_LEFT, 6, 60);

    s_lbl_desc = lv_label_create(panel);
    lv_obj_set_style_text_color(s_lbl_desc, lv_color_hex(0x1B4931), 0);
    lv_obj_set_width(s_lbl_desc, 200);
    lv_label_set_long_mode(s_lbl_desc, LV_LABEL_LONG_WRAP);
    lv_obj_align(s_lbl_desc, LV_ALIGN_TOP_LEFT, 6, 110);

    s_lbl_action = lv_label_create(panel);
    lv_obj_set_style_text_color(s_lbl_action, lv_color_hex(UI_INK), 0);
    lv_obj_align(s_lbl_action, LV_ALIGN_BOTTOM_MID, 0, -6);

    s_mascot = ui_pixel_mascot_create(s_scr, 101, 286);

    wifi_init_sta();
    update_guide_ui();
    lv_screen_load(s_scr);
}

void demo_lele_guide_exit(void) {
    if (s_scr) { lv_obj_delete(s_scr); s_scr = NULL; }
}

void demo_lele_guide_key(bsp_btn_t btn, bsp_btn_ev_t ev) {
    if (s_state == STATE_GUIDE) {
        if (btn == BSP_BTN_UP) {
            if (ev == BSP_BTN_PRESS) {
                s_state = STATE_LISTENING;
                show_listening_ui();
                s_recording = true;
                if (!s_rec_task) {
                    xTaskCreate(record_task_func, "rec_task", 4096, NULL, 5, &s_rec_task);
                }
            } else if (ev == BSP_BTN_CLICK || ev == BSP_BTN_LONG) {
                s_recording = false;
            }
        } else if (btn == BSP_BTN_DOWN && ev == BSP_BTN_CLICK) {
            s_spot_idx = (s_spot_idx + 1) % SPOTS_COUNT;
            update_guide_ui();
            ui_pixel_mascot_jump(s_mascot);
        } else if (btn == BSP_BTN_OK && ev == BSP_BTN_CLICK) {
            ui_pixel_mascot_jump(s_mascot);
        }
    } else if (s_state == STATE_PROPOSAL) {
        if (btn == BSP_BTN_OK && ev == BSP_BTN_CLICK) {
            s_state = STATE_DEPLOYING;
            if (bsp_lvgl_lock(500)) {
                lv_label_set_text(s_lbl_title, "🚀 正在提交并发布...");
                lv_label_set_text(s_lbl_sub, "流水线运行中...");
                bsp_lvgl_unlock();
            }
            if (s_udp_sock >= 0) {
                char confirm_pkt[768];
                snprintf(confirm_pkt, sizeof(confirm_pkt), "{\"type\":\"confirm_task\",\"title\":\"%s\",\"desc\":\"%s\",\"quiz\":\"%s\"}\n",
                         s_prop_title, s_prop_desc, s_prop_quiz);
                sendto(s_udp_sock, confirm_pkt, strlen(confirm_pkt), 0, (struct sockaddr *)&s_dest_addr, sizeof(s_dest_addr));
            }
        } else if (btn == BSP_BTN_DOWN && ev == BSP_BTN_CLICK) {
            s_state = STATE_GUIDE;
            update_guide_ui();
        }
    }
}
