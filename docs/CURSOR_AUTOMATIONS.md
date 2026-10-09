# Cursor Automations — task-overdue-watcher

Пошаговая настройка облачной автоматизации вместо Cowork на Windows.

## 1. Секреты (Automations → Environment)

| Переменная | Обязательна | Значение |
|------------|-------------|----------|
| `BITRIX24_WEBHOOK_URL` | да | Входящий webhook prod `laskov-partners` (vault Laskov-Clinic-Secrets) |
| `WATCHER_USER_ID` | нет | UID владельца / кому отчёт. По умолчанию `1` |
| `TASK_SCOPE` | нет | `member` (по умолчанию) или `all`. См. §1.1 |
| `BITRIX24_PORTAL` | нет | `https://laskov-partners.bitrix24.ru` |
| `BITRIX_DISK_STATE_FILE_ID` | для cloud | ID файла `state.json` на Disk (см. §3) |
| `STATE_FILE` | нет | `./data/state.json` — куда класть state в workspace |

Секреты кладутся в **Cloud Environment**, к которому привязана Automation (Dashboard → Cloud Agents → Environment → Secrets). В текст промпта вебхук не писать.

Scopes webhook: **task**, **im**, **user**, и **disk** (если state на Disk). Без `disk` падают `state_disk.py download/upload`.

## 1.1. Все задачи портала (`TASK_SCOPE=all`)

Сейчас скрипт по умолчанию передаёт `filter[MEMBER]=WATCHER_USER_ID`. Это задачи, где этот пользователь исполнитель, постановщик, соисполнитель или наблюдатель. Чужие задачи в выборку не попадают, даже если вебхук админский.

`TASK_SCOPE=all` убирает `MEMBER`. Дальше решает Битрикс, не скрипт:

| Кто создал вебхук | Что вернёт `tasks.task.list` без `MEMBER` |
|-------------------|------------------------------------------|
| Администратор портала | Все задачи портала |
| Руководитель отдела | Задачи своих сотрудников |
| Обычный сотрудник | Только задачи, к которым у него есть доступ (по сути свои) |

Пинг в чужую задачу (`task.commentitem.add`) тоже идёт от пользователя вебхука. Администратор может писать в любые задачи. Обычный пользователь получит отказ доступа, и задача попадёт в отчёт с ошибкой, без комментария.

Домен 2 (безответные комменты владельца) при `all` по-прежнему смотрит только задачи, где владелец участник: чужие чаты не читаем.

**Не включать `all` на старом `state.json` с `seeded: true`.** Новый охват скрипт сочтёт боевым и разошлёт пинги по всему бэклогу. Нужен отдельный state и первый прогон SEED.

## 1.2. Чего не хватает, если скилл «не работает» в Cloud

Скилл сам не стартует. Его выполняет Cloud Agent по Automation. Без пунктов ниже прогон либо не создаётся, либо сразу выходит с «задайте BITRIX24_WEBHOOK_URL», либо каждый раз делает SEED и никого не пингует.

1. Automation на [cursor.com/automations](https://cursor.com/automations): репозиторий `hemonc-team/task-overdue-watcher`, ветка `main`, cron `0 6 * * 1,4`, инструкции — `SKILL.md`.
2. У Automation выбран **Cloud Environment** (не «без окружения»). Иначе секреты в прогон не попадают: агент не видит `BITRIX24_WEBHOOK_URL`. Если окружение уже было и переменные пустые — открыть Automation, заново выбрать environment и сохранить.
3. В этом environment задан секрет `BITRIX24_WEBHOOK_URL`. Для постоянного state — ещё `BITRIX_DISK_STATE_FILE_ID`. Для всего портала — `TASK_SCOPE=all` и вебхук администратора.
4. Исходящий доступ с агента до `laskov-partners.bitrix24.ru` разрешён (egress окружения).
5. Первый прогон без перенесённого state — только SEED. Пинги начнутся со второго прогона, после `state_disk.py upload`.

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
| «Просрочено: 0», а задачи есть | Фильтр MEMBER / мета-статус / вебхук не админ при `TASK_SCOPE=all` / ошибка REST, которую старый скрипт глотал | Смотреть строку «я участник» или «весь портал». Ошибка `tasks.task.list` теперь роняет прогон, а не рисует ноль |
| Пустой SEED, следующий прогон сразу пингует | `--dry` раньше ставил `seeded=true` даже при нуле задач | `--dry` state не меняет. Ложный seed сбросить на `seeded: false` и `tasks: {}` |
| В отчёте ошибка доступа на пинге | Вебхук не админ, а задача чужая | Перевыпустить вебхук от администратора |
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
