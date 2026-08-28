// main/app_lele_guide.c —— 乐乐 AI 导游工牌原生全流程应用
#include "demo.h"
#include "bsp_audio.h"
#include "bsp_display.h"
#include "bsp_button.h"
#include "bsp_battery.h"
#include "ui_pixel.h"
#include "lvgl.h"
#include "lele_ota.h"

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
LV_FONT_DECLARE(lv_font_cn14);

static const char *TAG = "lele_guide";

static void update_guide_ui(void);
static void render_page(void);

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

static int s_spot_idx = 0;
static int s_page = 0;               // 内容页: 0=典故+好玩 1=好吃+考题

static int s_udp_sock = -1;
static struct sockaddr_in s_dest_addr;
static bool s_wifi_connected = false;

typedef struct {
    const char *spot;
    const char *city;
    const char *verse;
    const char *story;   // 典故
    const char *fun;     // 好玩的
    const char *food;    // 好吃的
    const char *quiz;    // 考题
} spot_info_t;

static const spot_info_t SPOTS[] = {
    // ---- 洛阳 ----
    {"白马寺", "洛阳", "白马驮经自宛延",
     "东汉皇帝夜梦金人，派使者西行，遇到两位印度高僧。白马驮着佛经佛像回到洛阳，建起中国第一座寺院，快2000岁了！",
     "寺里还有泰国、缅甸、印度风格的佛殿，一脚就像出国；找山门前的石马雕像合影；齐云塔是中国第一佛塔",
     "马寺钟声里的素斋，清凉解暑",
     "白马驮经讲的是哪座寺？"},
    {"龙门石窟", "洛阳", "谁家玉笛暗飞声",
     "古人花400多年在山崖上刻出2300多个洞窟、10万尊佛像！最大的卢舍那大佛17米高，脸照着武则天的样子刻的。",
     "东方蒙娜丽莎的微笑站哪都看着你；找2厘米高的迷你小佛像，万佛洞像蜂巢；晚上有灯光秀",
     "洛阳水席：牡丹燕菜，萝卜做出燕窝味",
     "龙门石窟最大的佛有多高？"},
    // ---- 南京 ----
    {"夫子庙", "南京", "旧时王谢堂前燕",
     "江南贡院是古代中国最大的考场，有两万个小隔间！考生要在两平米的小隔间里待九天六夜，唐伯虎也考过。中秋夜文德桥能看月亮分成两半。",
     "坐秦淮河画舫赏灯；看贡院的小隔间；逛小吃街",
     "鸭血粉丝汤、盐水鸭、糖芋苗",
     "夫子庙拜的夫子是谁？"},
    {"中华门瓮城", "南京", "千里澄江似练",
     "600年前明朝建的天下第一瓮城：三道城门，27个藏兵洞能藏3000士兵。敌人冲进来就像掉进大瓮，瓮中捉鳖！传说地基下埋着聚宝盆。",
     "数藏兵洞；城砖上刻着工匠名字；登城墙看南京全景",
     "南京大牌档：美龄粥、天王烤鸭包",
     "敌人进了瓮城会怎么样？"},
    // ---- 西安 ----
    {"秦始皇兵马俑", "西安", "秦王扫六合",
     "1974年农民打井挖出一个陶土人头，发现了2000多年前的地下军团！8000个俑千人千面没有两张脸相同，连鞋底针脚都刻了出来。",
     "找不同脸型的俑；看发型区别；找绿铠甲俑。刚出土时是彩色的，见空气几分钟就掉了",
     "临潼大盘鸡、柿面糊塌",
     "兵马俑为什么没有两张一样的脸？"},
    {"大雁塔", "西安", "春风得意马蹄疾",
     "真唐僧玄奘一个人走17年5万公里，从印度带回657部佛经。皇帝为他修了这座64米砖塔，1300年地震都震不倒！考中进士来塔上题名叫雁塔题名。",
     "看玄奘取经壁画；北广场音乐喷泉亚洲最大；登塔看西安全景",
     "长安大排档：毛笔酥，能吃的毛笔",
     "大雁塔是谁主持修建的？"},
    {"大唐不夜城", "西安", "人生得意须尽欢",
     "2100米的盛唐灯火长街，比操场绕20圈还长！整条街的灯笼城楼全亮着，像走进发光的大唐梦境。有不倒翁小姐姐、盛唐密盒。",
     "和李白对诗赢礼物；看不倒翁小姐姐牵手",
     "biangbiang面、镜糕、凉皮",
     "大唐不夜城有多长？"},
    {"西安城墙", "西安", "长乐安定永宁安",
     "中国保存最完整的古城墙，13.74公里，650岁了！糯米粥混黄土石灰夯筑，比水泥还结实，大炮都轰不倒。墙顶12米宽能跑马。",
     "骑自行车绕城墙一圈；数敌楼一共98座；永宁门看日落",
     "子午路张记肉夹馍+冰峰",
     "城墙为什么叫糯米墙？"},
    // ---- 渭南 ----
    {"华山西峰", "渭南", "举头红日近",
     "北宋7岁神童寇准爬华山写下这首诗！坐世界最长的西峰索道25分钟飞上山，山下汽车像蚂蚁。华山是沉香劈山救母的地方。",
     "坐西峰索道；找华山论剑石碑拍照；看沉香劈山石",
     "华阴大刀面",
     "咏华山是谁几岁写的？"},
    // ---- 三门峡 ----
    {"函谷关", "三门峡", "峰峦如聚，波涛如怒",
     "一夫当关万夫莫开！2500年前老子在这里写下5000字《道德经》。鸡鸣狗盗：食客学鸡叫骗开关门，帮孟尝君逃出秦国。",
     "找老子著经像；登关楼看古箭库；听紫气东来故事",
     "灵宝羊肉汤配脂油烧饼",
     "道德经是谁在哪写的？"},
    {"陕州地坑院", "三门峡", "见树不见村",
     "4000年的地下四合院：挖个大坑再凿洞当房子，冬暖夏凉不用空调！院子中间种一棵树，防止路人掉进坑里。",
     "下坑体验地下房子；看剪纸皮影戏；找渗水井",
     "陕州十大碗",
     "地坑院为什么中间种树？"},
    {"三门峡大坝", "三门峡", "黄河之水天上来",
     "新中国在黄河上建的第一座大坝！中流砥柱石被黄河冲了几千年都站着，船工见它就放心。传说三门是大禹用斧头劈开的。",
     "看中流砥柱石；坝上吹河风；了解人门神门鬼门",
     "观音堂牛肉、陕州菜卷",
     "中流砥柱是什么意思？"},
    // ---- 开封 ----
    {"清明上河园", "开封", "暖风熏得游人醉",
     "把《清明上河图》一比一搬到地上的宋朝主题园！虹桥没有一根钉子全靠木头叠起来。晚上大宋东京梦华演出，整个湖面都是舞台。",
     "看虹桥木结构；接王员外的绣球；看包公迎宾",
     "园内杏仁茶、炒凉粉",
     "清明上河图是谁画的？"},
    {"鼓楼夜市", "开封", "夜市直至三更尽",
     "开封是全中国夜市的发源地！宋朝取消宵禁后通宵营业。灌汤包四步口诀：轻轻提、慢慢移、先开窗、后喝汤！",
     "数夜市有多少种小吃；看桶子鸡制作；往巷子深处走更地道",
     "第一楼灌汤包、羊肉炕馍、杏仁茶",
     "灌汤包四步口诀是什么？"},
    {"龙亭公园", "开封", "王师北定中原日",
     "六朝皇宫遗址！脚下就是一千年前北宋的皇宫。潘杨二湖一浑一清：浑是奸臣潘仁美，清是忠臣杨家将。10月菊花展铺成花地毯。",
     "登72级台阶上龙亭大殿；看潘杨二湖对比；秋天赏菊",
     "开封桶子鸡",
     "潘杨二湖哪个清哪个浑？"},
};
#define SPOTS_COUNT (sizeof(SPOTS) / sizeof(SPOTS[0]))

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
    s_page = 0;
    render_page();
}

// 渲染当前页（s_page: 0=典故+好玩 1=好吃+考题）
static void render_page(void) {
    const spot_info_t *sp = &SPOTS[s_spot_idx];
    if (!bsp_lvgl_lock(500)) return;

    char title_buf[80];
    snprintf(title_buf, sizeof(title_buf), "%s · %s (%d/%d)",
             sp->city, sp->spot, s_spot_idx + 1, (int)SPOTS_COUNT);
    lv_label_set_text(s_lbl_title, title_buf);
    lv_label_set_text(s_lbl_sub, sp->verse);

    if (s_page == 0) {
        lv_label_set_text(s_lbl_poem, sp->story);
        lv_label_set_text(s_lbl_desc, sp->fun);
        lv_label_set_text(s_lbl_action, "OK:好吃和考题  下:下一景");
    } else {
        lv_label_set_text(s_lbl_poem, sp->food);
        lv_label_set_text(s_lbl_desc, sp->quiz);
        lv_label_set_text(s_lbl_action, "OK:回典故  下:下一景");
    }
    bsp_lvgl_unlock();
}

// OK 键切换页
static void next_page(void) {
    s_page = (s_page + 1) % 2;
    render_page();
}

static void show_listening_ui(void) {
    lv_label_set_text(s_lbl_title, "🎙️ 正在录制乐乐语音...");
    lv_label_set_text(s_lbl_sub, "请对着工牌麦克风说话");
    lv_label_set_text(s_lbl_poem, "正在采录 16kHz 高清音频...");
    lv_label_set_text(s_lbl_desc, "松开[上键]传送给大模型！");
    lv_label_set_text(s_lbl_action, "松开[上键]完成录音");
    bsp_lvgl_unlock();
}

static void show_proposal_ui(void) {
    char title_buf[256];
    snprintf(title_buf, sizeof(title_buf), "建议:%s", s_prop_title);
    lv_label_set_text(s_lbl_title, title_buf);
    
    char user_buf[384];
    snprintf(user_buf, sizeof(user_buf), "乐乐原话: \"%s\"", s_user_text);
    lv_label_set_text(s_lbl_sub, user_buf);
    
    lv_label_set_text(s_lbl_poem, s_prop_desc);
    
    char quiz_buf[256];
    snprintf(quiz_buf, sizeof(quiz_buf), "考考爸妈:%s", s_prop_quiz);
    lv_label_set_text(s_lbl_desc, quiz_buf);
    
    lv_label_set_text(s_lbl_action, "[OK 确认提交]  [下键 取消]");
    bsp_lvgl_unlock();
}

static void show_success_ui(void) {
    if (!bsp_lvgl_lock(500)) return;
    lv_label_set_text(s_lbl_title, "任务已成功发布！");
    lv_label_set_text(s_lbl_sub, "快看 iPad 上的新内容！");
    lv_label_set_text(s_lbl_poem, "网页已自动同步刷新");
    lv_label_set_text(s_lbl_desc, "正在播放小米 MiMo 语音讲解...");
    lv_label_set_text(s_lbl_action, "太棒啦！");
    bsp_lvgl_unlock();
}

static void record_task_func(void *arg) {
    (void)arg;
    bsp_audio_set_format(SAMPLE_RATE, 16, 1);

    // 流式方案：小分块采集并立即 UDP 发送，不需要大缓冲（C3 内存紧张）
    static int16_t chunk[CHUNK_SAMPLES];  // 512 samples = 1KB (static 避免栈压力)
    uint32_t total_samples = 0;
    bool send_ok = false;

    ESP_LOGI(TAG, "Recording started (streaming)...");

    // 先发 start 包
    if (s_udp_sock >= 0) {
        char notify[96];
        snprintf(notify, sizeof(notify), "{\"type\":\"voice_audio_start\"}\n");
        sendto(s_udp_sock, notify, strlen(notify), 0, (struct sockaddr *)&s_dest_addr, sizeof(s_dest_addr));
        send_ok = true;
    }

    size_t max_samples = (size_t)SAMPLE_RATE * MAX_REC_SEC;
    while (s_recording && total_samples < max_samples) {
        if (bsp_audio_read(chunk, CHUNK_SAMPLES * sizeof(int16_t)) != ESP_OK) break;
        if (send_ok && s_udp_sock >= 0) {
            sendto(s_udp_sock, chunk, CHUNK_SAMPLES * sizeof(int16_t), 0,
                   (struct sockaddr *)&s_dest_addr, sizeof(s_dest_addr));
            vTaskDelay(pdMS_TO_TICKS(2));  // 控制发送速率 ~= 实时
        }
        total_samples += CHUNK_SAMPLES;
    }

    ESP_LOGI(TAG, "Recording finished, %u samples", (unsigned)total_samples);
    if (send_ok && total_samples > 0) {
        char end_notify[64] = "{\"type\":\"voice_audio_end\"}\n";
        sendto(s_udp_sock, end_notify, strlen(end_notify), 0,
               (struct sockaddr *)&s_dest_addr, sizeof(s_dest_addr));
        ESP_LOGI(TAG, "Audio PCM stream sent!");
    } else {
        ESP_LOGW(TAG, "audio not sent (sock=%d samples=%u)", s_udp_sock, (unsigned)total_samples);
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

void lele_guide_wifi_event_handler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        s_wifi_connected = false;
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        s_wifi_connected = true;
        ESP_LOGI(TAG, "Wi-Fi connected! Setting up UDP socket...");
        // 延迟 5 秒检查云端固件版本（避免阻塞 UI 初始化）
        extern void lele_ota_delayed_check(void);
        lele_ota_delayed_check();
        
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

static bool s_wifi_started = false;
void lele_guide_start_wifi_impl(void) {
    if (s_wifi_started) {
        ESP_LOGI(TAG, "WiFi already started, skip re-init");
        return;
    }
    s_wifi_started = true;
    esp_err_t nvs_ret = nvs_flash_init();
    if (nvs_ret == ESP_ERR_NVS_NO_FREE_PAGES || nvs_ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }
    esp_netif_init();
    esp_event_loop_create_default();
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);

    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &lele_guide_wifi_event_handler, NULL, NULL);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &lele_guide_wifi_event_handler, NULL, NULL);

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
    // 护眼阅读模式：米色底 + 深灰字。flex 垂直流式布局，无固定空白
    s_scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_scr, lv_color_hex(0xF5F2E8), 0);
    lv_obj_remove_flag(s_scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_all(s_scr, 0, 0);

    // 垂直 flex 容器占满全屏
    lv_obj_t *col = lv_obj_create(s_scr);
    lv_obj_remove_flag(col, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(col, 240, 320);
    lv_obj_set_pos(col, 0, 0);
    lv_obj_set_style_bg_opa(col, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(col, 0, 0);
    lv_obj_set_style_pad_all(col, 0, 0);
    lv_obj_set_style_pad_column(col, 0, 0);
    lv_obj_set_style_pad_row(col, 4, 0);
    lv_obj_set_flex_flow(col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(col, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

    // 标题（自适应高度，约1-2行）
    s_lbl_title = lv_label_create(col);
    lv_obj_set_style_text_font(s_lbl_title, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_lbl_title, lv_color_hex(0x2B2B2B), 0);
    lv_obj_set_width(s_lbl_title, 232);
    lv_obj_set_style_pad_left(s_lbl_title, 5, 0);
    lv_label_set_long_mode(s_lbl_title, LV_LABEL_LONG_WRAP);

    // 诗句
    s_lbl_sub = lv_label_create(col);
    lv_obj_set_style_text_font(s_lbl_sub, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_lbl_sub, lv_color_hex(0x8B6F3E), 0);
    lv_obj_set_width(s_lbl_sub, 232);
    lv_obj_set_style_pad_left(s_lbl_sub, 5, 0);
    lv_label_set_long_mode(s_lbl_sub, LV_LABEL_LONG_DOT);

    // 主体：典故/美食（弹性占据剩余空间，可滚动查看超长内容）
    s_lbl_poem = lv_label_create(col);
    lv_obj_set_style_text_font(s_lbl_poem, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_lbl_poem, lv_color_hex(0x2B2B2B), 0);
    lv_obj_set_width(s_lbl_poem, 232);
    lv_obj_set_style_pad_left(s_lbl_poem, 5, 0);
    lv_obj_set_style_pad_right(s_lbl_poem, 5, 0);
    lv_obj_set_flex_grow(s_lbl_poem, 1);
    lv_label_set_long_mode(s_lbl_poem, LV_LABEL_LONG_WRAP);

    // 次要：好玩/考题（固定底部区域上方，2行）
    s_lbl_desc = lv_label_create(col);
    lv_obj_set_style_text_font(s_lbl_desc, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_lbl_desc, lv_color_hex(0x3D5A45), 0);
    lv_obj_set_width(s_lbl_desc, 232);
    lv_obj_set_style_pad_left(s_lbl_desc, 5, 0);
    lv_obj_set_style_pad_right(s_lbl_desc, 5, 0);
    lv_label_set_long_mode(s_lbl_desc, LV_LABEL_LONG_WRAP);

    // 操作提示
    s_lbl_action = lv_label_create(col);
    lv_obj_set_style_text_font(s_lbl_action, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_lbl_action, lv_color_hex(0x999999), 0);
    lv_obj_set_width(s_lbl_action, 232);
    lv_obj_set_style_pad_left(s_lbl_action, 5, 0);
    lv_label_set_long_mode(s_lbl_action, LV_LABEL_LONG_DOT);

    lele_guide_start_wifi_impl();
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
            } else if (ev == BSP_BTN_RELEASE || ev == BSP_BTN_CLICK) {
                // 抬起即发送（长按超过阈值时 CLICK 不再触发，RELEASE 兜底）
                s_recording = false;
            }
        } else if (btn == BSP_BTN_DOWN && ev == BSP_BTN_CLICK) {
            s_spot_idx = (s_spot_idx + 1) % SPOTS_COUNT;
            s_page = 0;
            render_page();
        } else if (btn == BSP_BTN_OK && ev == BSP_BTN_CLICK) {
            next_page();
        }
    } else if (s_state == STATE_PROPOSAL) {
        if (btn == BSP_BTN_OK && ev == BSP_BTN_CLICK) {
            s_state = STATE_DEPLOYING;
            if (bsp_lvgl_lock(500)) {
                lv_label_set_text(s_lbl_title, "正在提交并发布...");
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

// 供 main.c 调用：开机即启动 WiFi 与 OTA 检查
void main_start_wifi_and_ota(void) {
    lele_guide_start_wifi_impl();
}
