#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
task-overdue-watcher — надзиратель просроченных задач Bitrix24 + безответные комменты владельца вебхука.

Конфиг через env (см. .env.example):
  BITRIX24_WEBHOOK_URL — обязателен
  BITRIX24_PORTAL, WATCHER_USER_ID, STATE_FILE — опционально

Режимы:
  (авто) первый прогон при seeded=false -> SEED: только state, без commentitem.add
  --dry  — read-only
  --live — форс боевой (после seed)
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

# ---------- конфиг (env + CLI) ----------
def _parse_args():
    p = argparse.ArgumentParser(description="Bitrix24 task overdue watcher")
    p.add_argument("--dry", action="store_true", help="read-only, без записи на портал")
    p.add_argument("--live", action="store_true", help="форс боевой режим")
    p.add_argument("--state-file", dest="state_file", help="путь к state.json")
    return p.parse_args()


def _load_config(args):
    webhook = (
        os.environ.get("BITRIX24_WEBHOOK_URL")
        or os.environ.get("B24_WEBHOOK_URL")
        or ""
    ).strip().rstrip("/")
    if not webhook:
        print("ОШИБКА: задайте BITRIX24_WEBHOOK_URL", file=sys.stderr)
        sys.exit(2)
    portal = os.environ.get("BITRIX24_PORTAL", "https://laskov-partners.bitrix24.ru").rstrip("/")
    try:
        user_id = int(os.environ.get("WATCHER_USER_ID", "1"))
    except ValueError:
        print("ОШИБКА: WATCHER_USER_ID должен быть числом", file=sys.stderr)
        sys.exit(2)
    here = os.path.dirname(os.path.abspath(__file__))
    state_f = (
        args.state_file
        or os.environ.get("STATE_FILE")
        or os.path.join(here, "state.json")
    )
    return {
        "webhook": webhook + "/",
        "portal": portal,
        "user_id": user_id,
        "here": here,
        "state_f": state_f,
        "log_f": os.path.join(os.path.dirname(state_f), "run.log"),
        "lock_f": os.path.join(os.path.dirname(state_f), ".run.lock"),
        "dry": args.dry,
        "live": args.live,
    }


CFG = None  # заполняется в main()

BOT_MARK = "⁣"
BOT_TAG = "⁣[авто-контроль]"
FINAL_ST = {5, 6, 7}
OPEN_ST = {2, 3, 4}
N_CAP = 6
REASON_MIN = 15
D2_DAYS = 2
PING_GAP_H = 20
MSK = datetime.timezone(datetime.timedelta(hours=3))
LOCK_TTL = 20 * 60
DEPTH_WARN = []

TXT = {
    "S1": "Перенесите срок завершения задачи и укажите причину",
    "S2": "Укажите причину переноса срока",
    "S3": "Срок снова истёк. Перенесите срок и укажите причину",
}


# ---------- REST ----------
def call(method, params, retries=5):
    body = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(
        CFG["webhook"] + method + ".json",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                return json.load(e)
            except Exception:
                if i == retries - 1:
                    raise
        except Exception:
            if i == retries - 1:
                raise
        time.sleep(1.0)


def paginate(method, params):
    out, start = [], 0
    while True:
        p = dict(params)
        p["start"] = start
        r = call(method, p)
        res = r.get("result", {})
        tasks = res.get("tasks", res) if isinstance(res, dict) else res
        if not tasks:
            break
        out.extend(tasks)
        nxt = r.get("next")
        if nxt is None:
            break
        start = nxt
        time.sleep(0.25)
    return out


# ---------- utils ----------
def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None


def effective_deadline(dt):
    if dt is None:
        return None
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return dt.replace(hour=23, minute=59, second=59)
    return dt


BB = re.compile(r"\[/?[A-Za-z][^\]]*\]")


def strip_bb(msg):
    if not msg:
        return ""
    t = re.sub(r"\[QUOTE\].*?\[/QUOTE\]", " ", msg, flags=re.S | re.I)
    t = BB.sub(" ", t)
    t = t.replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def is_bot(msg):
    return bool(msg) and msg.startswith(BOT_MARK)


SYS_PAT = [
    "крайний срок измен",
    "задача просрочена",
    "задача почти просрочена",
    "вы назначены исполнителем",
    "вы добавлены наблюдателем",
    "вы добавлены соисполнителем",
    "вы добавлены постановщиком",
    "завершите задачу или передвиньте срок",
    "задача создана из шаблона",
    "срок выполнения истек",
    "изменен крайний срок",
]


def is_service(msg):
    t = strip_bb(msg).lower()
    return any(t.startswith(p) or p in t[:60] for p in SYS_PAT)


def is_noise(msg):
    return is_bot(msg) or is_service(msg)


def task_url(tid):
    uid = CFG["user_id"]
    return f"{CFG['portal']}/company/personal/user/{uid}/tasks/task/view/{tid}/"


# ---------- state ----------
def load_state():
    sf = CFG["state_f"]
    if os.path.exists(sf):
        try:
            with open(sf, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"version": 1, "seeded": False, "tasks": {}}


def save_state(st):
    st["last_run"] = datetime.datetime.now(MSK).isoformat()
    sf = CFG["state_f"]
    os.makedirs(os.path.dirname(os.path.abspath(sf)), exist_ok=True)
    tmp = sf + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, sf)


def logline(s):
    with open(CFG["log_f"], "a", encoding="utf-8") as f:
        f.write(s + "\n")


# ---------- per-task analysis ----------
def get_last_move(tid):
    r = call("tasks.task.history.list", {"taskId": tid})
    recs = r.get("result")
    if isinstance(recs, dict):
        recs = recs.get("list", [])
    dl = [x for x in (recs or []) if x.get("field") == "DEADLINE"]
    if not dl:
        return (False, None, None)
    dl.sort(key=lambda x: x.get("createdDate", ""))
    last = dl[-1]
    try:
        frm = int(last["value"]["from"])
        to = int(last["value"]["to"])
    except Exception:
        frm = to = 0
    moved_forward = to > frm
    mv = parse_dt(last.get("createdDate"))
    mover = (last.get("user") or {}).get("id")
    return (moved_forward, mv, int(mover) if mover else None)


def get_comments(chat_id, until_dt=None, max_pages=8):
    if not chat_id:
        return []
    out, last_id, reached = [], None, until_dt is None
    for _ in range(max_pages):
        p = {"DIALOG_ID": "chat" + str(chat_id), "LIMIT": 50}
        if last_id:
            p["LAST_ID"] = last_id
        msgs = ((call("im.dialog.messages.get", p).get("result") or {}).get("messages") or [])
        if not msgs:
            break
        for m in msgs:
            aid = m.get("author_id")
            if not aid:
                continue
            out.append(
                {
                    "ID": m.get("id"),
                    "AUTHOR_ID": aid,
                    "POST_DATE": m.get("date"),
                    "POST_MESSAGE": m.get("text") or "",
                }
            )
        ids = [m.get("id") for m in msgs if m.get("id")]
        oldest_id = min(ids) if ids else None
        oldest_dt = parse_dt(msgs[-1].get("date"))
        if until_dt and oldest_dt and oldest_dt <= until_dt:
            reached = True
            break
        if not oldest_id or oldest_id == last_id or len(msgs) < 50:
            reached = True
            break
        last_id = oldest_id
        time.sleep(0.15)
    if not reached:
        DEPTH_WARN.append(str(chat_id))
    return out


def has_reason(comments, mover_id, move_date):
    if not mover_id or not move_date:
        return False
    for c in comments:
        if is_noise(c.get("POST_MESSAGE")):
            continue
        try:
            aid = int(c.get("AUTHOR_ID"))
        except Exception:
            continue
        if aid != mover_id:
            continue
        pd = parse_dt(c.get("POST_DATE"))
        if not pd or pd <= move_date:
            continue
        if len(strip_bb(c.get("POST_MESSAGE"))) >= REASON_MIN:
            return True
    return False


def answered_since(comments, since_dt):
    if not since_dt:
        return False
    uid = CFG["user_id"]
    for c in comments:
        if is_noise(c.get("POST_MESSAGE")):
            continue
        try:
            if int(c.get("AUTHOR_ID")) == uid:
                continue
        except (TypeError, ValueError):
            continue
        pd = parse_dt(c.get("POST_DATE"))
        if pd and pd > since_dt:
            return True
    return False


# ---------- main ----------
def _run():
    mode = "auto"
    if CFG["dry"]:
        mode = "dry"
    if CFG["live"]:
        mode = "live"
    st = load_state()
    seed = not st.get("seeded")
    if mode == "live":
        seed = False
    do_post = (not seed) and (mode != "dry")

    uid = CFG["user_id"]
    now = datetime.datetime.now(MSK)
    report = {"pinged": [], "escalate": [], "domain2": [], "self": [], "capped": [], "warn": []}
    overdue_ids = set()

    nows = now.strftime("%Y-%m-%dT%H:%M:%S+03:00")
    cand = paginate(
        "tasks.task.list",
        {
            "filter": {"MEMBER": uid, "<DEADLINE": nows, "CLOSED_DATE": ""},
            "select": [
                "ID",
                "TITLE",
                "DEADLINE",
                "STATUS",
                "RESPONSIBLE_ID",
                "CREATED_BY",
                "GROUP_ID",
                "CHAT_ID",
            ],
        },
    )

    overdue = []
    for t in cand:
        try:
            status = int(t.get("status"))
        except Exception:
            continue
        if status in FINAL_ST:
            continue
        if status not in OPEN_ST:
            continue
        dl = effective_deadline(parse_dt(t.get("deadline")))
        if not dl or dl >= now:
            continue
        overdue.append((t, dl))
        overdue_ids.add(str(t.get("id")))

    for t, dl in overdue:
        tid = str(t.get("id"))
        try:
            resp = int(t.get("responsibleId") or 0)
        except Exception:
            resp = 0
        rec = st["tasks"].get(tid, {})
        if not rec.get("first_overdue_date"):
            rec["first_overdue_date"] = now.isoformat()
        rec["overdue_run_count"] = rec.get("overdue_run_count", 0) + 1
        rec["last_seen_deadline"] = t.get("deadline")

        try:
            moved, move_date, mover = get_last_move(tid)
            prev_p = parse_dt(rec.get("last_ping_date"))
            depth = min([d for d in (move_date, prev_p) if d], default=None)
            comments = get_comments(t.get("chatId"), until_dt=depth)
        except Exception as e:
            report["warn"].append(
                f"задача {tid}: ошибка чтения ({type(e).__name__}) — пропущена, пинг не слался"
            )
            continue
        reason = has_reason(comments, mover, move_date) if moved else False
        state = "S1" if not moved else ("S3" if reason else "S2")
        rec["last_state"] = state
        time.sleep(0.2)

        info = {"id": tid, "title": t.get("title"), "url": task_url(tid), "state": state, "resp": resp}

        if resp == uid:
            rec.setdefault("pings_sent", 0)
            rec.setdefault("unanswered_pings", 0)
            report["self"].append(info)
            st["tasks"][tid] = rec
            save_state(st)
            continue

        prev_ping = parse_dt(rec.get("last_ping_date"))
        if prev_ping and not answered_since(comments, prev_ping):
            rec["unanswered_pings"] = rec.get("unanswered_pings", 0)
        else:
            rec["unanswered_pings"] = 0

        if rec.get("unanswered_pings", 0) >= N_CAP:
            rec["capped"] = True
            report["capped"].append(info)
            st["tasks"][tid] = rec
            save_state(st)
            continue

        if seed:
            rec.setdefault("pings_sent", 0)
            rec.setdefault("unanswered_pings", 0)
            st["tasks"][tid] = rec
            save_state(st)
            continue

        prev_ping_dt = parse_dt(rec.get("last_ping_date"))
        if prev_ping_dt and (now - prev_ping_dt) < datetime.timedelta(hours=PING_GAP_H):
            st["tasks"][tid] = rec
            save_state(st)
            continue

        if do_post:
            text = BOT_TAG + " " + TXT[state]
            r = call("task.commentitem.add", [int(tid), {"POST_MESSAGE": text}])
            cid = r.get("result")
            ok = str(cid).isdigit()
            if ok:
                rec["pings_sent"] = rec.get("pings_sent", 0) + 1
                rec["unanswered_pings"] = rec.get("unanswered_pings", 0) + 1
                rec["last_ping_date"] = now.isoformat()
                info["pings"] = rec["unanswered_pings"]
                st["tasks"][tid] = rec
                save_state(st)
                time.sleep(1.0)
                back = get_comments(t.get("chatId"))
                info["verified"] = any(str(x.get("ID")) == str(cid) for x in back[:5])
                report["pinged"].append(info)
                if rec["unanswered_pings"] >= 2:
                    report["escalate"].append(info)
            else:
                info["error"] = r.get("error_description") or r.get("error") or str(r)[:120]
                report["pinged"].append(info)
            time.sleep(0.3)
        st["tasks"][tid] = rec
        save_state(st)

    open_tasks = paginate(
        "tasks.task.list",
        {
            "filter": {"MEMBER": uid, "CLOSED_DATE": ""},
            "select": ["ID", "TITLE", "STATUS", "DEADLINE", "CHAT_ID"],
        },
    )
    xcheck = set()
    for t in open_tasks:
        if str(t.get("status")) not in ("2", "3", "4"):
            continue
        dl = effective_deadline(parse_dt(t.get("deadline")))
        if dl and dl < now:
            xcheck.add(str(t.get("id")))
    if xcheck != overdue_ids:
        missed = xcheck - overdue_ids
        extra = overdue_ids - xcheck
        report["warn"].append(
            f"РАСХОЖДЕНИЕ детекции просрочки: осн.путь={len(overdue_ids)}, "
            f"клиент-контроль={len(xcheck)}; пропущены={sorted(missed)}; лишние={sorted(extra)}."
        )

    cutoff = now - datetime.timedelta(days=D2_DAYS)
    d2_scanned = 0
    for t in open_tasks:
        if str(t.get("status")) not in ("2", "3", "4"):
            continue
        tid = str(t.get("id"))
        try:
            comments = get_comments(t.get("chatId"), until_dt=cutoff)
        except Exception as e:
            report["warn"].append(f"домен2, задача {tid}: ошибка чтения ({type(e).__name__})")
            continue
        d2_scanned += 1
        time.sleep(0.15)
        last_live = None
        for c in comments:
            if is_noise(c.get("POST_MESSAGE")):
                continue
            last_live = c
            break
        if not last_live:
            continue
        try:
            aid = int(last_live.get("AUTHOR_ID"))
        except Exception:
            continue
        if aid != uid:
            continue
        pd = parse_dt(last_live.get("POST_DATE"))
        if pd and pd < cutoff:
            days = (now - pd).days
            report["domain2"].append(
                {"id": tid, "title": t.get("title"), "url": task_url(tid), "days": days}
            )

    if DEPTH_WARN:
        report["warn"].append(
            "не добрали глубину чата (исчерпан лимит страниц) для чатов: "
            + ", ".join(sorted(set(DEPTH_WARN)))
            + " — причина/ответ могли остаться за горизонтом чтения"
        )
    st["seeded"] = True
    save_state(st)

    rep = build_report(report, seed, len(overdue), d2_scanned, now)
    logline(
        f"[{now.isoformat()}] mode={'seed' if seed else ('dry' if not do_post else 'live')} "
        f"overdue={len(overdue)} pinged={len(report['pinged'])} "
        f"escalate={len(report['escalate'])} domain2={len(report['domain2'])} "
        f"self={len(report['self'])} capped={len(report['capped'])}"
    )
    print(rep)
    if do_post:
        send_report(rep)
    return rep


def build_report(r, seed, n_over, d2_scanned, now):
    L = []
    hdr = "🟡 Контроль задач (SEED — комменты не отправлялись)" if seed else "🔴 Контроль задач"
    L.append(f"{hdr} — {now.strftime('%d.%m.%Y %H:%M')} МСК")
    for w in r.get("warn", []):
        L.append(f"‼️ {w}")
    L.append(
        f"Просрочено (я участник): {n_over} | пингов: {len(r['pinged'])} | "
        f"эскалация: {len(r['escalate'])} | безответных комментов моих: {len(r['domain2'])}"
    )
    if r["pinged"]:
        L.append("\n— A. Отправлены пинги:")
        for x in r["pinged"]:
            e = f" ⚠ошибка:{x['error']}" if x.get("error") else ""
            v = "" if x.get("verified", True) else " ⚠не подтверждён read-back"
            L.append(
                f"  • [{x['state']}] {x['title']} (пинг №{x.get('pings', '?')}){e}{v}\n    {x['url']}"
            )
    if r["escalate"]:
        L.append("\n— B. ≥2 безответных пинга, всё ещё просрочено:")
        for x in r["escalate"]:
            L.append(f"  • {x['title']} (пингов: {x.get('pings')})\n    {x['url']}")
    if r["capped"]:
        L.append(f"\n— Достигли потолка {N_CAP} пингов (пинги остановлены):")
        for x in r["capped"]:
            L.append(f"  • {x['title']}\n    {x['url']}")
    if r["domain2"]:
        L.append(f"\n— C. Мои комменты без ответа >{D2_DAYS}д (открытые задачи):")
        for x in r["domain2"]:
            L.append(f"  • {x['title']} — {x['days']}д без ответа\n    {x['url']}")
    if r["self"] and seed:
        L.append(f"\n(пропущено self-ping задач, где я исполнитель: {len(r['self'])})")
    if not (r["pinged"] or r["escalate"] or r["domain2"] or r["capped"]):
        L.append("\nВсё чисто по критериям контроля.")
    return "\n".join(L)


def send_report(text):
    uid = CFG["user_id"]
    r = call("im.notify.personal.add", {"USER_ID": uid, "MESSAGE": text})
    if not r.get("result"):
        call("im.message.add", {"DIALOG_ID": str(uid), "MESSAGE": text})


def acquire_lock():
    lf = CFG["lock_f"]
    if os.path.exists(lf):
        try:
            age = time.time() - os.path.getmtime(lf)
        except OSError:
            age = 0
        if age < LOCK_TTL:
            return False
        try:
            os.remove(lf)
        except OSError:
            pass
    with open(lf, "w") as fh:
        fh.write(str(os.getpid()))
    return True


def release_lock():
    lf = CFG["lock_f"]
    try:
        os.remove(lf)
        return
    except OSError:
        pass
    try:
        old = time.time() - (LOCK_TTL * 10)
        os.utime(lf, (old, old))
    except OSError:
        pass


def main():
    global CFG
    args = _parse_args()
    CFG = _load_config(args)
    if not acquire_lock():
        print("Прогон уже идёт (свежий .run.lock) — выходим, чтобы не задублировать пинги.")
        return None
    try:
        return _run()
    finally:
        release_lock()


if __name__ == "__main__":
    main()
