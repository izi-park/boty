#!/usr/bin/env python3

import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import izi_box_worker as worker


MOSCOW = ZoneInfo("Europe/Moscow")
TEST_VK_ID = -999
BACKUP_DIR = Path("/root/fleet/izi_box_test_backups")


def log(message):
    print(message, flush=True)


def read_profile(headers, contractor_id, title):
    for attempt in range(1, 6):
        profile, error = worker.get_profile(headers, contractor_id)

        if profile:
            return profile

        log(f"{title}: попытка {attempt}/5, ошибка: {error}")
        time.sleep(20 * attempt)

    return None


def switch_rule(headers, contractor_id, target_rule, original_comment, title):
    for attempt in range(1, 6):
        current = read_profile(headers, contractor_id, f"{title} — чтение")

        if not current:
            continue

        current_rule = (current.get("account") or {}).get("work_rule_id")

        if current_rule == target_rule:
            log(f"{title}: правило уже подтверждено")
            return True

        ok, error = worker.put_rule(
            headers,
            contractor_id,
            current,
            target_rule,
            original_comment,
        )

        if ok:
            log(f"{title}: Fleet подтвердил правило")
            return True

        log(f"{title}: попытка {attempt}/5, ошибка: {error}")
        time.sleep(20 * attempt)

    return False


def main():
    worker.init_db()
    headers, _park_id = worker.fleet_settings()

    with worker.connect() as conn:
        binding = conn.execute(
            """
            SELECT b.contractor_id, c.full_name
            FROM bindings b
            LEFT JOIN courier_cache c USING (contractor_id)
            WHERE b.vk_user_id = ?
            """,
            (TEST_VK_ID,),
        ).fetchone()

    if not binding:
        log("❌ Тестовая привязка Дениса не найдена")
        return 1

    contractor_id = binding["contractor_id"]
    name = binding["full_name"] or "Тестовый курьер"

    log("=" * 70)
    log("ТЕСТ ИЗИ БОКС: ИСХОДНОЕ → НУЛЕВОЙ → ИСХОДНОЕ")
    log("=" * 70)
    log(f"Курьер: {name}")

    before = read_profile(headers, contractor_id, "Исходный профиль")

    if not before:
        log("❌ Не удалось получить исходный профиль. Ничего не менялось.")
        return 1

    original_rule = (before.get("account") or {}).get("work_rule_id")
    original_comment = (before.get("profile") or {}).get("comment") or ""

    log(f"Исходное правило: {original_rule}")

    if original_rule not in worker.SAFE_BASE_RULES:
        log("❌ Исходное правило не входит в безопасный список. Ничего не менялось.")
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(MOSCOW).strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"denis-before-zero-{stamp}.json"
    backup_path.write_text(
        json.dumps(before, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(backup_path, 0o600)
    log(f"✅ Резервная копия: {backup_path}")

    zero_was_seen = False
    restore_ok = False

    try:
        log("ШАГ 1: устанавливаем НУЛЕВОЙ")
        zero_was_seen = switch_rule(
            headers,
            contractor_id,
            worker.RULE_ZERO,
            original_comment,
            "Установка НУЛЕВОГО",
        )

        if zero_was_seen:
            log("✅ НУЛЕВОЙ реально подтверждён Fleet")
            time.sleep(5)
        else:
            log("⚠️ Установка не подтверждена. Переходим к обязательному возврату.")

    finally:
        log("ШАГ 2: обязательно возвращаем исходное правило")
        current = read_profile(headers, contractor_id, "Проверка перед возвратом")

        if not current:
            log("❌ Не удалось прочитать профиль перед возвратом")
        else:
            current_rule = (current.get("account") or {}).get("work_rule_id")
            log(f"Правило перед возвратом: {current_rule}")

            if current_rule == original_rule:
                restore_ok = True
            elif current_rule == worker.RULE_ZERO:
                restore_ok = switch_rule(
                    headers,
                    contractor_id,
                    original_rule,
                    original_comment,
                    "Возврат исходного правила",
                )
            else:
                log("❌ Обнаружено постороннее ручное правило — его не перезаписываем")

    final_profile = read_profile(headers, contractor_id, "Финальная проверка")
    final_rule = None

    if final_profile:
        final_rule = (final_profile.get("account") or {}).get("work_rule_id")

    log(f"Финальное правило: {final_rule}")

    if final_rule == original_rule and restore_ok:
        if zero_was_seen:
            log("✅ ТЕСТ ЗАВЕРШЁН: НУЛЕВОЙ сработал, исходная комиссия восстановлена")
            return 0

        log("⚠️ Исходная комиссия сохранена, но НУЛЕВОЙ не был подтверждён")
        return 1

    log("❌ ВНИМАНИЕ: возврат не подтверждён. Нужна ручная проверка Fleet.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
