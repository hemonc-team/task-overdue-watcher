# Агент: task-overdue-watcher

Репозиторий [hemonc-team/task-overdue-watcher](https://github.com/hemonc-team/task-overdue-watcher) — надзиратель задач Bitrix24 для клиники доктора Ласкова.

## Правила

- **Не читать** `.env` / credential-файлы напрямую. Только `.env.example`.
- **Не коммитить** `state.json`, `run.log`, вебхук, ПДн.
- Секреты — vault Laskov-Clinic-Secrets или env Automations.
- Первый cloud-прогон **без** миграции state → только SEED.

## Точка входа

1. `SKILL.md` — алгоритм для automation
2. `docs/CURSOR_AUTOMATIONS.md` — настройка cron и Disk
3. `overdue_watcher.py` — исполнение

## Контекст клиники

См. `Laskov-Clinic/AGENTS.md` и `.cursor/rules/healthcare-context.mdc`.
