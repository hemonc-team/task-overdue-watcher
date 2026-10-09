# task-overdue-watcher

Надзиратель просроченных задач Bitrix24: пингует исполнителей и шлёт сводку владельцу вебхука. Расписание — **2×/неделю** (понедельник и четверг, утро МСK).

## Что внутри

| Файл | Зачем |
|------|--------|
| `overdue_watcher.py` | Основной скрипт (REST, без Chrome) |
| `state_disk.py` | Скачать/загрузить `state.json` с Bitrix Disk для cloud |
| `SKILL.md` | Инструкция для Cursor Automation / Claude Code |
| `docs/CURSOR_AUTOMATIONS.md` | Пошаговая настройка automation |
| `state.json.example` | Пустой шаблон state |

## Быстрый старт (локально)

```bash
git clone https://github.com/hemonc-team/task-overdue-watcher.git
cd task-overdue-watcher
cp .env.example .env   # заполнить BITRIX24_WEBHOOK_URL локально, не коммитить

python3 overdue_watcher.py --dry   # проверка без записи на портал
python3 overdue_watcher.py         # seed или live (по state.json)
```

Секреты: vault **Laskov-Clinic-Secrets** или env в Cursor Automations.

## Cursor Automations

Полная инструкция: **[docs/CURSOR_AUTOMATIONS.md](docs/CURSOR_AUTOMATIONS.md)**

Кратко:

1. Репозиторий: `hemonc-team/task-overdue-watcher`, ветка `main`
2. Расписание: `0 6 * * 1,4` (09:00 МСK = 06:00 UTC)
3. Env в Cloud Environment: `BITRIX24_WEBHOOK_URL`, для всего портала `TASK_SCOPE=all` (вебхук администратора), опционально `BITRIX_DISK_STATE_FILE_ID`
4. Первый прогон — с переносом старого `state.json` (см. миграцию в docs)

## Миграция с Cowork / Dropbox

Старый боевой state лежал в `claude-b24/scheduled/task-overdue-watcher/state.json` (Dropbox). Чтобы **не получить спам-волну** повторного seed:

1. Скопировать `state.json` (должен быть `"seeded": true`)
2. Залить на Bitrix Disk → получить `BITRIX_DISK_STATE_FILE_ID`
3. Первый cloud-прогон: `state_disk.py download` → `--dry` → live

## Связанные репозитории

- [claude-b24](https://github.com/hemonc-team/claude-b24) — исходное зеркало в монорепо
- [lead-analysis-skill](https://github.com/hemonc-team/lead-analysis-skill) — ежедневный анализ лидов

## Org

[hemonc-team](https://github.com/hemonc-team) · портал prod: `laskov-partners`
