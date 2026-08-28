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
    // ---- 南京 ----
    {"夫子庙", "南京", "旧时王谢堂前燕",
     "夫子庙是祭祀孔子的庙宇。旁边的江南贡院是古代中国最大的科举考场，有两万多个小隔间，考生要连考九天六夜，吃住都在号舍里，唐伯虎、吴承恩都考过。中秋夜站在文德桥上，还能看到月亮被分成两半的奇景。",
     "坐秦淮河画舫看花灯；进贡院钻钻最小号舍；去乌衣巷念刘禹锡的诗",
     "鸭血粉丝汤、盐水鸭、糖芋苗",
     "江南贡院考的是什么？"},
    {"中华门瓮城", "南京", "千里澄江似练",
     "600多年前明朝建的天下第一瓮城，原名聚宝门。三道城门、27个藏兵洞能藏三千士兵，敌人冲进来就像掉进大瓮——瓮中捉鳖！每块城砖都刻着工匠名字，砖不合格要追责重烧，所以650年还稳稳站着。",
     "数藏兵洞；找城砖上的名字；登城墙看南京全景",
     "南京大牌档：美龄粥、天王烤鸭包",
     "敌人进了瓮城会怎么样？"},
    // ---- 洛阳 ----
    {"白马寺", "洛阳", "白马驮经自宛延",
     "东汉皇帝夜梦金人，派人西行求法，遇到两位印度高僧，用白马驮着佛经回到洛阳，建起中国第一座官办寺院，快2000岁了。寺里齐云塔是中国第一佛塔，传说塔顶的金蛤蟆还会应声。",
     "国际佛殿苑一次出国：泰国金顶、缅甸龙柱、印度圆顶；和石马合影",
     "马寺钟声里的素斋，清凉解暑",
     "中国第一座官办寺院是哪座？"},
    {"龙门石窟", "洛阳", "谁家玉笛暗飞声",
     "古人花400多年，在伊河两岸山崖上刻出2300多个洞窟、10万多尊佛像！最大的卢舍那大佛17米高，耳朵就有1.9米，传说照着武则天的样子刻的。万佛洞一万五千尊小佛，密得像蜂巢。",
     "找东方蒙娜丽莎的微笑；万佛洞数小佛；过桥去白园拜白居易",
     "洛阳水席：牡丹燕菜，萝卜做出燕窝味",
     "卢舍那大佛有多高？"},
    // ---- 西安 ----
    {"秦始皇兵马俑", "西安", "秦王扫六合",
     "1974年农民打井挖出陶土人头，唤醒了2000多年前的地下军团！8000个俑千人千面，没有两张脸相同，连鞋底针脚都刻了出来。刚出土时是彩色的，几分钟就氧化消失。铜车马号称青铜之冠。",
     "找绿脸俑；看跪射俑的鞋底纹；看铜车马",
     "临潼大盘鸡、柿面糊塌、火晶柿子",
     "兵马俑是哪一年被发现的？"},
    {"大雁塔", "西安", "春风得意马蹄疾",
     "真唐僧玄奘西行17年、5万里，带回657部佛经，皇帝专门修塔放经书，就是大雁塔。塔七层64米，1300年多次地震都没倒。唐朝考中进士的人来塔下题名叫雁塔题名，白居易27岁考中，得意地写：十七人中最少年。",
     "看玄奘取经壁画；北广场音乐喷泉亚洲最大；晚上看塔身亮灯",
     "长安大排档：毛笔酥、镜糕",
     "大雁塔是谁主持修建的？"},
    {"大唐不夜城", "西安", "人生得意须尽欢",
     "2100米的盛唐灯火长街，比操场绕20圈还长！晚上灯笼城楼全亮，像走进发光的大唐梦境。不倒翁小姐姐一牵手全网羡慕；盛唐密盒里房玄龄和杜如晦抽人上台答题，笑翻全场。",
     "和李白对诗赢礼物；牵不倒翁小姐姐的手；举手冲上盛唐密盒",
     "biangbiang面、镜糕、凉皮",
     "盛唐密盒的两位大人是谁？"},
    {"西安城墙", "西安", "长乐安定永宁安",
     "中国保存最完整的古城墙，13.74公里，650多岁！糯米粥拌黄土石灰夯筑，比水泥还结实，大炮都轰不倒。墙顶宽12到14米，能跑马。四座主城门连起来是长安永安的好彩头。",
     "租自行车绕城墙一圈；数敌楼；永宁门看日落和灯光秀",
     "子午路张记肉夹馍配冰峰",
     "西安城墙周长多少公里？"},
    // ---- 渭南 ----
    {"华山西峰", "渭南", "举头红日近",
     "华山是沉香劈山救母的地方，西峰顶上真有一道斧劈石！北宋神童寇准7岁爬华山，写下只有天在上，更无山与齐。西峰索道长4211米、爬升894米，像坐火箭上山，山下汽车小得像蚂蚁。",
     "坐西峰索道；和华山论剑石碑拍照；摸摸沉香劈山石",
     "华阴大刀面",
     "《咏华山》是谁几岁写的？"},
    // ---- 三门峡 ----
    {"函谷关", "三门峡", "天开函谷壮关中",
     "一夫当关，万夫莫开！2500年前老子骑青牛路过，关令尹喜望见紫气东来，请他写下5000字《道德经》，如今是全球发行量最大的书之一。成语鸡鸣狗盗也出自这里：食客学鸡叫骗开关门，救了孟尝君。",
     "找老子著经像和青牛；登关楼看古箭库；听紫气东来的故事",
     "灵宝羊肉汤配脂油烧饼",
     "《道德经》是谁在哪写的？"},
    {"陕州地坑院", "三门峡", "见树不见村",
     "4000年的地下四合院：在地上挖个六七米深的大方坑，四壁凿窑洞当房子，冬暖夏凉不用空调！见树不见村，进村不见房，闻声不见人，说的就是它。院子中央种棵树，是提醒路人别掉坑的警示牌。",
     "下坑住住地下窑洞；看剪纸皮影戏；找院里的渗水井",
     "陕州十大碗",
     "地坑院院子中间为什么种树？"},
    {"三门峡大坝", "三门峡", "黄河之水天上来",
     "新中国在黄河上建的第一座大型水坝！传说大禹治水用神斧把山劈成人门、神门、鬼门，三门峡因此得名。坝下中流砥柱石被黄河冲了几千年仍稳稳站着，船工看见它就知道前面安全了。",
     "看中流砥柱石；坝顶吹河风看黄河；找张公岛",
     "观音堂牛肉、陕州菜卷",
     "中流砥柱是什么意思？"},
    // ---- 开封 ----
    {"清明上河园", "开封", "暖风熏得游人醉",
     "把张择端的《清明上河图》一比一搬上地的宋朝主题园！五米多高的虹桥没有一根钉子，全靠木头搭叠。一进园就穿越了：包公迎宾、王员外抛绣球招婿、斗鸡木偶戏，晚上整个湖面都是大舞台。",
     "接王员外的绣球；看包公迎宾；虹桥上数木拱",
     "园内杏仁茶、炒凉粉",
     "《清明上河图》是谁画的？"},
    {"鼓楼夜市", "开封", "夜市直至三更尽",
     "开封是全中国夜市的发源地！宋朝取消宵禁后夜市通宵营业，《东京梦华录》记载的美食摊比现在还热闹。灌汤包有四步口诀：轻轻提、慢慢移、先开窗、后喝汤，一口鲜掉眉毛。",
     "数夜市有多少种小吃；看桶子鸡制作；钻巷子深处找地道味",
     "第一楼灌汤包、羊肉炕馍、杏仁茶",
     "灌汤包四步口诀是什么？"},
    {"龙亭公园", "开封", "王师北定中原日",
     "脚下就是六朝皇宫遗址，北宋皇宫就埋在72级台阶下面！潘杨二湖一浑一清：浑的是奸臣潘仁美家的湖，清的是忠臣杨家将家的湖，老百姓说湖水都分忠奸。每年10月菊花铺成花地毯。",
     "登72级台阶上龙亭大殿；对比潘杨二湖；秋天赏菊",
     "开封桶子鸡、花生糕",
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
    char para_buf[300];
    snprintf(title_buf, sizeof(title_buf), "%s · %s (%d/%d)",
             sp->city, sp->spot, s_spot_idx + 1, (int)SPOTS_COUNT);
    lv_label_set_text(s_lbl_title, title_buf);
    lv_label_set_text(s_lbl_sub, sp->verse);

    if (s_page == 0) {
        lv_label_set_text(s_lbl_poem, sp->story);
        snprintf(para_buf, sizeof(para_buf), "\n%s", sp->fun);
        lv_label_set_text(s_lbl_desc, para_buf);
    } else {
        lv_label_set_text(s_lbl_poem, sp->food);
        snprintf(para_buf, sizeof(para_buf), "\n%s", sp->quiz);
        lv_label_set_text(s_lbl_desc, para_buf);
    }
    lv_label_set_text(s_lbl_action, "OK:下一页  下:下一景");
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
    lv_obj_set_style_pad_row(col, 6, 0);
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

    // 主体：典故/美食（流式布局,文字往下堆,余量留在页尾）
    s_lbl_poem = lv_label_create(col);
    lv_obj_set_style_text_font(s_lbl_poem, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_lbl_poem, lv_color_hex(0x2B2B2B), 0);
    lv_obj_set_width(s_lbl_poem, 232);
    lv_obj_set_style_pad_left(s_lbl_poem, 5, 0);
    lv_obj_set_style_pad_right(s_lbl_poem, 5, 0);
    lv_label_set_long_mode(s_lbl_poem, LV_LABEL_LONG_WRAP);

    // 次要：好玩/考题（空一行作段落间隔,最多一行）
    s_lbl_desc = lv_label_create(col);
    lv_obj_set_style_text_font(s_lbl_desc, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_lbl_desc, lv_color_hex(0x3D5A45), 0);
    lv_obj_set_width(s_lbl_desc, 232);
    lv_obj_set_style_pad_left(s_lbl_desc, 5, 0);
    lv_obj_set_style_pad_right(s_lbl_desc, 5, 0);
    lv_label_set_long_mode(s_lbl_desc, LV_LABEL_LONG_WRAP);

    // 操作提示（固定屏幕底部,不随内容流式排布）
    s_lbl_action = lv_label_create(s_scr);
    lv_obj_set_style_text_font(s_lbl_action, &lv_font_cn14, 0);
    lv_obj_set_style_text_color(s_lbl_action, lv_color_hex(0x999999), 0);
    lv_obj_set_width(s_lbl_action, 232);
    lv_obj_set_style_pad_left(s_lbl_action, 5, 0);
    lv_label_set_long_mode(s_lbl_action, LV_LABEL_LONG_DOT);
    lv_obj_align(s_lbl_action, LV_ALIGN_BOTTOM_MID, 0, -4);

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
