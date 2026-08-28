// 无线固件升级（HTTP OTA）—— 从云服务器拉取新固件
#include "lele_ota.h"
#include "esp_http_client.h"
#include "esp_https_ota.h"
#include "esp_ota_ops.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
#include <esp_app_desc.h>

static const char *TAG = "lele_ota";

#define CURRENT_FW_VERSION "1.0.0"
#define OTA_VER_URL  "http://124.221.187.167:8088/firmware/version.txt"
#define OTA_BIN_URL  "http://124.221.187.167:8090/firmware/latest.bin"

// 极简 HTTP GET（raw socket，只用于读 version.txt 这类小文件）
static bool http_get_small_once(const char *host, int port, const char *path, char *out, int out_max)
{
    struct sockaddr_in da = {0};
    da.sin_family = AF_INET;
    da.sin_port = htons(port);
    inet_pton(AF_INET, host, &da.sin_addr);
    int sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) { ESP_LOGE(TAG, "sock fail"); return false; }
    struct timeval tv = { .tv_sec = 8, .tv_usec = 0 };
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    if (connect(sock, (struct sockaddr *)&da, sizeof(da)) != 0) {
        ESP_LOGE(TAG, "connect fail errno=%d", errno);
        close(sock); return false;
    }
    char req[256];
    int rl = snprintf(req, sizeof(req), "GET %s HTTP/1.0\r\nHost: %s\r\n\r\n", path, host);
    if (write(sock, req, rl) < 0) { close(sock); return false; }
    // 读全部响应
    static char resp[2048];
    int total = 0, n;
    while (total < (int)sizeof(resp) - 1 &&
           (n = read(sock, resp + total, sizeof(resp) - 1 - total)) > 0) {
        total += n;
    }
    close(sock);
    resp[total] = 0;
    // 取 body（\r\n\r\n 之后）
    char *body = strstr(resp, "\r\n\r\n");
    if (!body) return false;
    body += 4;
    int bl = strlen(body);
    if (bl <= 0 || bl >= out_max) return false;
    memcpy(out, body, bl + 1);
    // 去尾部换行
    while (bl > 0 && (out[bl-1] == 10 || out[bl-1] == 13)) out[--bl] = 0;
    return true;
}


// 带重试的小文件 GET（网络偶发失败时重试 3 次）
static bool http_get_small(const char *host, int port, const char *path, char *out, int out_max)
{
    for (int attempt = 1; attempt <= 3; attempt++) {
        if (http_get_small_once(host, port, path, out, out_max)) return true;
        vTaskDelay(pdMS_TO_TICKS(1500));
    }
    return false;
}

bool lele_ota_is_new_version(const char *ver_url)
{
    (void)ver_url;
    // 运行中固件的真实版本（OTA 升级后会变化）
    const esp_app_desc_t *app = esp_app_get_description();
    const char *local_ver = app->version;
    char remote_ver[32] = {0};
    bool ok = false;
    for (int attempt = 1; attempt <= 3 && !ok; attempt++) {
        ok = http_get_small_once("124.221.187.167", 8090, "/firmware/version.txt", remote_ver, sizeof(remote_ver));
        if (!ok) {
            ESP_LOGW(TAG, "version fetch attempt %d failed", attempt);
            vTaskDelay(pdMS_TO_TICKS(2000));
        }
    }
    if (!ok) {
        ESP_LOGE(TAG, "version fetch failed after 3 retries");
        return false;
    }
    bool need = (strcmp(remote_ver, local_ver) != 0);
    ESP_LOGI(TAG, "remote ver=%s local=%s need_update=%d", remote_ver, local_ver, need);
    return need;
}

void lele_ota_check_and_update(const char *fw_url)
{
    ESP_LOGI(TAG, "Starting OTA from %s", fw_url);
    esp_http_client_config_t config = {
        .url = fw_url,
        .timeout_ms = 20000,
        .buffer_size = 8192,
    };
    esp_https_ota_config_t ota_config = {
        .http_config = &config,
    };
    esp_err_t ret = esp_https_ota(&ota_config);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "OTA success, rebooting...");
        esp_restart();
    } else {
        ESP_LOGE(TAG, "OTA failed: %s", esp_err_to_name(ret));
    }
}

static void ota_check_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "ota_check_task started, waiting 5s...");
    vTaskDelay(pdMS_TO_TICKS(5000));
    ESP_LOGI(TAG, "checking for firmware update...");
    // 基础连通性诊断:TCP 直连 8090
    {
        struct sockaddr_in da = {0};
        da.sin_family = AF_INET;
        da.sin_port = htons(8090);
        inet_pton(AF_INET, "124.221.187.167", &da.sin_addr);
        int tsock = socket(AF_INET, SOCK_STREAM, 0);
        if (tsock >= 0) {
            int r = connect(tsock, (struct sockaddr *)&da, sizeof(da));
            ESP_LOGI(TAG, "raw tcp connect to 8090: %d (errno=%d)", r, errno);
            close(tsock);
        } else {
            ESP_LOGE(TAG, "socket create failed");
        }
    }
    if (lele_ota_is_new_version(OTA_VER_URL)) {
        lele_ota_check_and_update(OTA_BIN_URL);
    } else {
        ESP_LOGI(TAG, "firmware up to date");
    }
    vTaskDelete(NULL);
}

void lele_ota_delayed_check(void)
{
    BaseType_t r = xTaskCreate(ota_check_task, "ota_check", 8192, NULL, 5, NULL);
    ESP_LOGI(TAG, "delayed_check xTaskCreate=%d (pdPASS=%d)", (int)r, (int)pdPASS);
}
