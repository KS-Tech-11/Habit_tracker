#!/usr/bin/env python3
"""
Habit Tracker - Enhanced Edition
Features: CRUD, streaks with grace days, notes per check-in,
edit habits, today's pending view, export, theme toggle,
uniqueness constraints, and robust connection handling.
"""

import sqlite3
import csv
import json
import os
import sys
from datetime import datetime, date, timedelta
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "habits.db")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            last_completed TEXT,
            streak INTEGER NOT NULL DEFAULT 0,
            max_streak INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (date('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            completed_at TEXT NOT NULL,
            note TEXT,
            FOREIGN KEY (habit_id) REFERENCES habits(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Seed default settings if missing
    defaults = {
        "theme": "light",
        "grace_days": "1",
        "reminder_time": "",
    }
    for k, v in defaults.items():
        c.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
        )

    conn.commit()


# ---------------------------------------------------------------------------
# Styling / theme
# ---------------------------------------------------------------------------

THEMES = {
    "light": {
        "border": "\u2500",
        "header": "\u250c\u2500\u2500\u2500",
        "title_bg": "\033[44m\033[97m",
        "title_fg": "\033[0m",
        "ok": "\033[32m",
        "warn": "\033[33m",
        "err": "\033[31m",
        "dim": "\033[2m",
        "reset": "\033[0m",
    },
    "dark": {
        "border": "\u2500",
        "header": "\u250c\u2500\u2500\u2500",
        "title_bg": "\033[47m\033[30m",
        "title_fg": "\033[0m",
        "ok": "\033[92m",
        "warn": "\033[33m",
        "err": "\033[91m",
        "dim": "\033[2m",
        "reset": "\033[0m",
    },
}


def t(col: str) -> str:
    """Return ANSI escape for a theme colour key."""
    theme = get_setting("theme")
    return THEMES.get(theme, THEMES["light"]).get(col, "")


def styled_title(text: str, width: int = 60) -> str:
    pad = width - len(text) - 2
    left = pad // 2
    right = pad - left
    return (
        f"{t('title_bg')} {text} " + " " * right + f"{t('reset')}"
    )


def divider(width: int = 60) -> str:
    return t("border") * width + t("reset")


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def add_habit(conn: sqlite3.Connection, name: str) -> Optional[int]:
    """Add a new habit. Returns new id or None on error."""
    name = name.strip()
    if not name:
        print(f"{t('err')}Name cannot be empty.{t('reset')}")
        return None

    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO habits (name, last_completed, streak, max_streak) VALUES (?, NULL, 0, 0)",
            (name,),
        )
        conn.commit()
        hid = c.lastrowid
        print(f"{t('ok')}\u2713 Habit '{name}' added (ID {hid}).{t('reset')}")
        return hid
    except sqlite3.IntegrityError:
        print(f"{t('err')}\u2717 Habit '{name}' already exists.{t('reset')}")
        return None


def show_habits(
    conn: sqlite3.Connection,
    filter_text: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list:
    """Return habits list; optionally filtered, limited, offset."""
    c = conn.cursor()
    query = "SELECT id, name, streak, max_streak, last_completed, created_at FROM habits"
    params: list = []

    if filter_text:
        query += " WHERE name LIKE ?"
        params.append(f"%{filter_text}%")

    query += " ORDER BY id"

    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
        query += " OFFSET ?"
        params.append(offset)

    c.execute(query, params)
    rows = c.fetchall()

    # Pretty print
    if not rows:
        print(f"\n{t('dim')}No habits found.{t('reset')}")
        return rows

    print()
    hdr = f"{t('ok')}{'ID':<4} | {'Habit':<18} | {'Streak':<7} | {'Record':<7} | {'Last Done'}{t('reset')}"
    print(hdr)
    print(divider(len(hdr)))

    for r in rows:
        last = r["last_completed"] if r["last_completed"] else "Never"
        print(
            f"{r['id']:<4} | {r['name']:<18} | {r['streak']:<7} | {r['max_streak']:<7} | {last}"
        )

    # Pagination summary
    total_q = "SELECT COUNT(*) FROM habits"
    if filter_text:
        total_q += " WHERE name LIKE ?"
        c.execute(total_q, (f"%{filter_text}%",))
    else:
        c.execute(total_q)
    total = c.fetchone()[0]

    if limit and offset + limit < total:
        print(f"{t('dim')}\u23a7 Page {offset//limit + 1} \u2014 {min(offset+limit, total)} of {total}{t('reset')}")

    return rows


def today_pending(conn: sqlite3.Connection) -> None:
    """Show habits not yet completed today."""
    c = conn.cursor()
    today = date.today().isoformat()
    c.execute(
        """
        SELECT id, name, streak, max_streak
        FROM habits
        WHERE last_completed IS NULL OR last_completed != ?
        ORDER BY id
        """,
        (today,),
    )
    rows = c.fetchall()

    if not rows:
        print(f"\n{t('ok')}\u2605 Nothing pending \u2014 you've completed everything today!{t('reset')}")
        return

    print(f"\n{t('header')}Today's Pending{t('reset')}")
    print(divider(45))
    print(f"  {'ID':<4} | {'Habit':<20} | {'Streak'}")
    print(divider(45))
    for r in rows:
        print(f"  {r['id']:<4} | {r['name']:<20} | {r['streak']}")
    print(divider(45))
    print(f"{t('dim')}{len(rows)} habit(s) left for today.{t('reset')}")


def complete_habit(conn: sqlite3.Connection, habit_id: int, note: Optional[str] = None) -> bool:
    """Mark a habit complete. Returns True on success."""
    c = conn.cursor()
    c.execute(
        "SELECT last_completed, streak, max_streak FROM habits WHERE id = ?", (habit_id,)
    )
    row = c.fetchone()

    if not row:
        print(f"{t('err')}\u2717 Habit ID {habit_id} not found.{t('reset')}")
        return False

    last_str, current_streak, max_streak = row
    today = date.today()

    # --- Streak logic with grace days ---
    grace = int(get_setting("grace_days", "1"))

    if last_str:
        last_date = datetime.strptime(last_str, "%Y-%m-%d").date()
        delta = (today - last_date).days

        if delta == 0:
            print(f"{t('warn')}\u26a0 Already completed today!{t('reset')}")
            return False
        elif delta == 1:
            current_streak += 1
        elif delta <= grace + 1:
            # Within grace window: streak continues but doesn't grow
            print(
                f"{t('warn')}\u26a0 Missed {delta - 1} day(s) "
                f"(within {grace}-day grace). Streak holds at {current_streak}.{t('reset')}"
            )
        else:
            print(
                f"{t('err')}\u274c Missed {delta - 1} day(s). Streak reset to 1.{t('reset')}"
            )
            current_streak = 1
    else:
        current_streak = 1  # first completion ever

    new_max = max(current_streak, max_streak)

    # --- Record the completion with optional note ---
    c.execute(
        "INSERT INTO completions (habit_id, completed_at, note) VALUES (?, ?, ?)",
        (habit_id, today.isoformat(), note),
    )
    c.execute(
        "UPDATE habits SET last_completed = ?, streak = ?, max_streak = ? WHERE id = ?",
        (today.isoformat(), current_streak, new_max, habit_id),
    )
    conn.commit()

    print(
        f"{t('ok')}\u2b50 Done! Streak: {current_streak}"
        + (f" \u2605 Personal Best: {new_max}" if new_max > 1 else "")
        + f"{t('reset')}"
    )
    if note:
        print(f"{t('dim')}Note: {note}{t('reset')}")
    return True


def edit_habit(conn: sqlite3.Connection, habit_id: int, new_name: Optional[str] = None) -> bool:
    """Edit a habit's name. Returns True on success."""
    c = conn.cursor()
    c.execute("SELECT name FROM habits WHERE id = ?", (habit_id,))
    row = c.fetchone()

    if not row:
        print(f"{t('err')}\u2717 Habit ID {habit_id} not found.{t('reset')}")
        return False

    old_name = row["name"]

    if new_name is None:
        new_name = input(f"New name for '{old_name}': ").strip()

    if not new_name:
        print(f"{t('err')}Name cannot be empty.{t('reset')}")
        return False

    if new_name == old_name:
        print(f"{t('dim')}No change.{t('reset')}")
        return True

    try:
        c.execute("UPDATE habits SET name = ? WHERE id = ?", (new_name, habit_id))
        conn.commit()
        print(f"{t('ok')}\u2713 Renamed '{old_name}' \u2192 '{new_name}'.{t('reset')}")
        return True
    except sqlite3.IntegrityError:
        print(f"{t('err')}\u2717 Habit '{new_name}' already exists.{t('reset')}")
        return False


def delete_habit(conn: sqlite3.Connection, habit_id: int, force: bool = False) -> bool:
    """Delete a habit. Returns True on success."""
    c = conn.cursor()
    c.execute("SELECT name FROM habits WHERE id = ?", (habit_id,))
    row = c.fetchone()

    if not row:
        print(f"{t('err')}\u2717 Habit ID {habit_id} not found.{t('reset')}")
        return False

    if not force:
        confirm = input(
            f"Delete '{row['name']}' (ID {habit_id})? This removes all history. (y/n): "
        )
        if confirm.lower() != "y":
            print(f"{t('dim')}Cancelled.{t('reset')}")
            return False

    c.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
    conn.commit()
    print(f"{t('ok')}\u2713 Deleted '{row['name']}'.{t('reset')}")
    return True


def habit_history(conn: sqlite3.Connection, habit_id: int, days: int = 30) -> None:
    """Show recent completions for a habit."""
    c = conn.cursor()
    start_date = (date.today() - timedelta(days=days)).isoformat()

    c.execute(
        """
        SELECT completed_at, note FROM completions
        WHERE habit_id = ? AND completed_at >= ?
        ORDER BY completed_at DESC
        """,
        (habit_id, start_date),
    )
    rows = c.fetchall()

    c.execute("SELECT name FROM habits WHERE id = ?", (habit_id,))
    name_row = c.fetchone()
    name = name_row["name"] if name_row else f"ID {habit_id}"

    print(f"\n{t('header')}History: {name}{t('reset')}")
    if not rows:
        print(f"{t('dim')}No completions in the last {days} days.{t('reset')}")
        return

    print(divider(50))
    print(f"  {'Date':<12} | {'Note'}")
    print(divider(50))
    for r in rows:
        note = r["note"] or ""
        print(f"  {r['completed_at']:<12} | {note}")
    print(divider(50))
    print(f"{t('dim')}{len(rows)} completion(s) shown.{t('reset')}")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_csv(conn: sqlite3.Connection, path: Optional[str] = None) -> None:
    """Export habits + completions to CSV."""
    if path is None:
        path = input("Export file path (CSV): ").strip()
    if not path:
        print(f"{t('err')}No path given.{t('reset')}")
        return

    c = conn.cursor()

    habits = c.execute("SELECT id, name, streak, max_streak, last_completed, created_at FROM habits").fetchall()
    completions = c.execute(
        "SELECT c.id, c.habit_id, h.name, c.completed_at, c.note FROM completions c JOIN habits h ON c.habit_id = h.id ORDER BY c.completed_at DESC"
    ).fetchall()

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)

        w.writerow(["=== HABITS ==="])
        w.writerow(["id", "name", "streak", "max_streak", "last_completed", "created_at"])
        for h in habits:
            w.writerow(h)

        w.writerow([])
        w.writerow(["=== COMPLETIONS ==="])
        w.writerow(["id", "habit_id", "habit_name", "completed_at", "note"])
        for c2 in completions:
            w.writerow(c2)

    print(f"{t('ok')}\u2713 Exported to {path}{t('reset')}")


def export_json(conn: sqlite3.Connection, path: Optional[str] = None) -> None:
    """Export habits + completions to JSON."""
    if path is None:
        path = input("Export file path (JSON): ").strip()
    if not path:
        print(f"{t('err')}No path given.{t('reset')}")
        return

    c = conn.cursor()
    habits = c.execute("SELECT id, name, streak, max_streak, last_completed, created_at FROM habits").fetchall()
    completions = c.execute(
        "SELECT c.id, c.habit_id, h.name as habit_name, c.completed_at, c.note FROM completions c JOIN habits h ON c.habit_id = h.id ORDER BY c.completed_at DESC"
    ).fetchall()

    data = {
        "exported_at": date.today().isoformat(),
        "habits": [dict(h) for h in habits],
        "completions": [dict(c2) for c2 in completions],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"{t('ok')}\u2713 Exported to {path}{t('reset')}")


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

MENU = """
\033[1m===== HABIT TRACKER =====\033[0m
  1. Add new habit
  2. Show all habits
  3. Today's pending
  4. Check-in (complete habit)
  5. Edit habit
  6. Delete habit
  7. Habit history
  8. Export (CSV / JSON)
  9. Settings (theme / grace days)
  10. Exit
"""

SETTINGS_MENU = """
\033[1m--- Settings ---\033[0m
  1. Toggle theme (light / dark)
  2. Set grace days (missed days before reset)
  3. Back
"""


def prompt_note() -> Optional[str]:
    """Ask for an optional note on check-in."""
    resp = input("Add a note? (optional, press Enter to skip): ").strip()
    return resp if resp else None


def main() -> None:
    conn = get_db()
    try:
        init_db(conn)

        while True:
            print(styled_title("HABIT TRACKER", 50))
            print(MENU)
            choice = input("Choose an option: ").strip()

            if choice == "1":
                name = input("Enter habit name: ")
                add_habit(conn, name)

            elif choice == "2":
                filt = input("Filter by name? (Enter to skip): ").strip()
                show_habits(conn, filter_text=filt if filt else None)

            elif choice == "3":
                today_pending(conn)

            elif choice == "4":
                show_habits(conn)
                try:
                    hid = int(input("\nEnter habit ID to check-in: "))
                    note = prompt_note()
                    complete_habit(conn, hid, note)
                except ValueError:
                    print(f"{t('err')}\u2717 Please enter a valid number.{t('reset')}")

            elif choice == "5":
                show_habits(conn)
                try:
                    hid = int(input("\nEnter habit ID to edit: "))
                    edit_habit(conn, hid)
                except ValueError:
                    print(f"{t('err')}\u2717 Please enter a valid number.{t('reset')}")

            elif choice == "6":
                show_habits(conn)
                try:
                    hid = int(input("\nEnter habit ID to delete: "))
                    delete_habit(conn, hid)
                except ValueError:
                    print(f"{t('err')}\u2717 Please enter a valid number.{t('reset')}")

            elif choice == "7":
                show_habits(conn)
                try:
                    hid = int(input("\nEnter habit ID to view history: "))
                    days = input("Look back how many days? (default 30): ").strip()
                    d = int(days) if days else 30
                    habit_history(conn, hid, d)
                except ValueError:
                    print(f"{t('err')}\u2717 Please enter a valid number.{t('reset')}")

            elif choice == "8":
                export_menu(conn)

            elif choice == "9":
                settings_menu(conn)

            elif choice == "10":
                print(f"\n{t('ok')}Goodbye! Keep up the good work.{t('reset')}\n")
                break

            else:
                print(f"{t('err')}\u2717 Invalid choice. Try again.{t('reset')}")

            input("\nPress Enter to continue...")

    finally:
        conn.close()


def export_menu(conn: sqlite3.Connection) -> None:
    print(f"\n{t('header')}--- Export ---{t('reset')}")
    print("  1. CSV")
    print("  2. JSON")
    print("  3. Back")
    choice = input("Choose: ").strip()
    if choice == "1":
        export_csv(conn)
    elif choice == "2":
        export_json(conn)
    # else: back


def settings_menu(conn: sqlite3.Connection) -> None:
    while True:
        print(f"\n{SETTINGS_MENU}")
        print(f"{t('dim')}Current: theme={get_setting('theme')}, grace={get_setting('grace_days')} days{t('reset')}")
        choice = input("Choose: ").strip()

        if choice == "1":
            cur = get_setting("theme", "light")
            nxt = "dark" if cur == "light" else "light"
            set_setting("theme", nxt)
            print(f"{t('ok')}\u2713 Theme set to {nxt}.{t('reset')}")

        elif choice == "2":
            cur = get_setting("grace_days", "1")
            val = input(f"Grace days (currently {cur}): ").strip()
            if val.isdigit() and int(val) >= 0:
                set_setting("grace_days", val)
                print(f"{t('ok')}\u2713 Grace days set to {val}.{t('reset')}")
            else:
                print(f"{t('err')}\u2717 Enter a non-negative integer.{t('reset')}")

        elif choice == "3":
            break
        else:
            print(f"{t('err')}\u2717 Invalid.{t('reset')}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{t('dim')}\nInterrupted. Goodbye.{t('reset')}")
        sys.exit(0)
