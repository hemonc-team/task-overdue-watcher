# implementation-notes (выдержка)

Исторический журнал разработки. Полная версия — в [claude-b24](https://github.com/hemonc-team/claude-b24) `scheduled/task-overdue-watcher/`.

## Ключевые инварианты (не ломать)

1. **Первый прогон = SEED** — без commentitem.add, иначе спам по бэклогу.
2. **Write-through state** — после каждого пинга сразу `save_state`, иначе дубли (инцидент 20.07.2026).
3. **Фильтр просрочки** — `MEMBER` + `<DEADLINE` + `CLOSED_DATE=""`; статус {2,3,4} на клиенте (мета-STATUS в фильтре ломает выборку).
4. **Комментарии задачи** — через `im.dialog.messages.get`, не legacy `task.commentitem.getlist`.
5. **Self-ping** — RESPONSIBLE == WATCHER_USER_ID → не пинговать.
6. **Потолок** — 6 безответных пингов → stop + эскалация.
7. **Lock** — `.run.lock` TTL 20 мин против параллельных прогонов.

## Баг «0 просроченных» (2026-07-16)

**Причина:** `STATUS` в filter REST = мета-статус (-1 просрочена), а не реальный status 2/3/4.

**Фикс:** фильтровать `CLOSED_DATE=""`, статус отсеивать в Python.

## Миграция в cloud (2026-08-28)

- Вебhook вынесен в `BITRIX24_WEBHOOK_URL`
- State — Bitrix Disk (`state_disk.py`) или локальный `STATE_FILE`
- Источник истины репо: `hemonc-team/task-overdue-watcher`
