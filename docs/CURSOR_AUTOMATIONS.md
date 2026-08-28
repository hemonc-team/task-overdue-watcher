# Cursor Automations — task-overdue-watcher

Пошаговая настройка облачной автоматизации вместо Cowork на Windows.

## 1. Секреты (Automations → Environment)

| Переменная | Обязательна | Значение |
|------------|-------------|----------|
| `BITRIX24_WEBHOOK_URL` | да | Входящий webhook prod `laskov-partners` (vault Laskov-Clinic-Secrets) |
| `WATCHER_USER_ID` | нет | UID владельца / кому отчёт. По умолчанию `1` |
| `BITRIX24_PORTAL` | нет | `https://laskov-partners.bitrix24.ru` |
| `BITRIX_DISK_STATE_FILE_ID` | для cloud | ID файла `state.json` на Disk (см. §3) |
| `STATE_FILE` | нет | `./data/state.json` — куда класть state в workspace |

Scopes webhook: **task**, **im**, **user** (минимум для `tasks.*`, `im.dialog.messages.get`, `im.notify.personal.add`).

## 2. Automation в Cursor

| Поле | Значение |
|------|----------|
| **Name** | `task-overdue-watcher` |
| **Description** | Просроченные задачи Б24 + безответные комменты. Пн/Чт 09:00 МСK |
| **Trigger** | Cron `0 6 * * 1,4` (09:00 Europe/Moscow = 06:00 UTC) |
| **Repo** | `hemonc-team/task-overdue-watcher`, branch `main` |
| **Skill / Instructions** | Содержимое `SKILL.md` из репо (или `@SKILL.md`) |

Cloud compute: включить в [Cloud Agents dashboard](https://cursor.com/dashboard?tab=cloud-agents).

## 3. State на Bitrix Disk (важно для cloud)

У cloud-агента **эфемерный диск** — без Disk каждый прогон = новый SEED.

### Однократная подготовка

1. Взять бэкап `state.json` из старого Cowork (`claude-b24/scheduled/task-overdue-watcher/` на Dropbox).
2. На Bitrix Disk создать файл, например `Автоматизации/task-overdue-watcher/state.json`.
3. Залить бэкап. Через REST получить ID:

```bash
# пример: найти файл (подставить свой webhook из env)
curl -s -X POST "$BITRIX24_WEBHOOK_URL/disk.folder.getchildren.json" \
  -H 'Content-Type: application/json' \
  -d '{"id": "<FOLDER_ID>"}' | jq '.result[] | select(.NAME=="state.json") | .ID'
```

4. ID записать в `BITRIX_DISK_STATE_FILE_ID`.

### Каждый прогон (делает агент по SKILL.md)

```bash
python3 state_disk.py download
python3 overdue_watcher.py
python3 state_disk.py upload
```

## 4. Первый запуск после миграции

| Шаг | Команда | Ожидание |
|-----|---------|----------|
| 1 | `state_disk.py download` | state с `seeded: true` |
| 2 | `overdue_watcher.py --dry` | отчёт в stdout, **без** commentitem.add |
| 3 | Проверить число просроченных и предупреждения | |
| 4 | `overdue_watcher.py` | LIVE: пинги + отчёт в Б24 |
| 5 | `state_disk.py upload` | state обновлён на Disk |

**Не пропускать шаг 1.** Без старого state cloud сделает SEED и не будет пинговать до второго прогона — это нормально для нового контура, но теряются счётчики `unanswered_pings`.

## 5. Режимы скрипта

| Режим | Как | Пинги | Отчёт в Б24 |
|-------|-----|-------|-------------|
| SEED | `seeded=false` в state | нет | нет (только stdout) |
| LIVE | `seeded=true`, без `--dry` | да | да |
| DRY | `--dry` | нет | нет |

`--live` — форс LIVE даже если state ещё не seeded (осторожно).

## 6. Мониторинг

- **run.log** — рядом с state (локально или в workspace; в cloud не персистентен — ориентир: stdout automation run)
- **Отчёт** — уведомление Bitrix24 владельцу (`WATCHER_USER_ID`)
- **Lock** — `.run.lock` не даёт двум прогонам идти параллельно (TTL 20 мин)

## 7. Troubleshooting

| Симптом | Причина | Действие |
|---------|---------|----------|
| «Просрочено: 0», а задачи есть | Фильтр MEMBER / мета-статус | Смотреть `warn` в отчёте; см. `docs/implementation-notes.md` |
| Дубли пингов | Параллельный прогон / краш до save state | Проверить `.run.lock`; state upload после прогона |
| SEED каждый раз | Нет Disk / не upload state | Настроить §3 |
| `insufficient_scope` | Webhook без task/im | Пересоздать webhook с нужными scopes |

## 8. Отличие от Cowork

| | Cowork (Windows) | Cursor Automation |
|--|------------------|-------------------|
| State | Dropbox рядом со скриптом | Bitrix Disk или ручной upload |
| Запуск | ПК Ласкова включён | Cloud agent по cron |
| Chrome | не нужен | не нужен |
| Отчёт | im.notify + дубль в Cowork | im.notify + stdout run |
