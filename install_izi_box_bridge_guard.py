#!/usr/bin/env python3

import os
import py_compile
import shutil
from datetime import datetime


BRIDGE_PATH = "/root/vk_incoming_bridge.py"
IMPORT_ANCHOR = "import sqlite3\n"
IMPORT_BLOCK = (
    "import sqlite3\n"
    "import sys\n"
    "sys.path.insert(0, '/root/bot/boty')\n"
    "from izi_box_bridge_guard import should_skip_izi_box\n"
)
LOOP_ANCHOR = '        attachments = full.get("attachments") or []\n'
LOOP_BLOCK = (
    '        attachments = full.get("attachments") or []\n\n'
    '        if should_skip_izi_box(out, peer_id, from_id, text):\n'
    '            print(f"[BRIDGE SKIP IZI BOX] vk_id={from_id}", flush=True)\n'
    '            continue\n'
)


def main():
    with open(BRIDGE_PATH, "r", encoding="utf-8") as file:
        source = file.read()

    if "from izi_box_bridge_guard import should_skip_izi_box" in source:
        print("✅ Защита Изи Бокс уже установлена")
        return

    if source.count(IMPORT_ANCHOR) != 1:
        raise RuntimeError("Не найден однозначный участок импортов")

    if source.count(LOOP_ANCHOR) != 1:
        raise RuntimeError("Не найден однозначный участок обработки сообщений")

    updated = source.replace(IMPORT_ANCHOR, IMPORT_BLOCK, 1)
    updated = updated.replace(LOOP_ANCHOR, LOOP_BLOCK, 1)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{BRIDGE_PATH}.bak-before-izi-box-{stamp}"
    candidate = f"{BRIDGE_PATH}.izi-box-new"

    with open(candidate, "w", encoding="utf-8") as file:
        file.write(updated)

    py_compile.compile(candidate, doraise=True)
    shutil.copy2(BRIDGE_PATH, backup)
    os.replace(candidate, BRIDGE_PATH)

    print("✅ Защита игровых сообщений установлена")
    print("Резервная копия:", backup)


if __name__ == "__main__":
    main()
