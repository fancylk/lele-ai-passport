#pragma once
#include <stdbool.h>

// 检查并执行 OTA（阻塞，成功后自动重启）
// fw_url 例: http://124.221.187.167:8088/firmware/latest.bin
void lele_ota_check_and_update(const char *fw_url);
bool lele_ota_is_new_version(const char *ver_url);
