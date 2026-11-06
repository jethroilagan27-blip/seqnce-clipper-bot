"""Admin commands for a deployment with accounts (AUTH_ENABLED=true).

Run from backend/:   uv run python -m app.admin <command>

  invite [--email E] [--days 7]     create a one-time invite code (shown once; only its hash is stored)
  create-user EMAIL [--admin]       create an account directly (asks for the password)
  users                             list accounts with today's usage
  disable EMAIL / enable EMAIL      block / unblock a user (also signs them out)
  set-limits EMAIL [--videos N] [--chats N]   per-user daily limits ("default" resets to the server default)
  make-admin EMAIL                  admins have no quotas and can see every job
  reset-password EMAIL              set a new password and sign the user out everywhere

Passwords are read from a hidden prompt, or from the SEQNCE_ADMIN_PASSWORD environment variable for
scripts. They are never accepted on the command line, so they don't end up in your shell history.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import Sequence

from . import auth, db


def _password(email: str) -> str:
    password = os.environ.get("SEQNCE_ADMIN_PASSWORD")
    if password is None:
        password = getpass.getpass(f"New password for {email}: ")
        if password != getpass.getpass("Repeat it: "):
            raise SystemExit("The passwords don't match.")
    problem = auth.password_problem(password, email)
    if problem:
        raise SystemExit(problem)
    return password


def _user(email_raw: str) -> dict:
    email = auth.normalize_email(email_raw)
    row = db.get_user_by_email(email) if email else None
    if row is None:
        raise SystemExit(f"No account for {email_raw!r}.")
    return row


def create_user(email_raw: str, password: str, *, is_admin: bool = False) -> int:
    email = auth.normalize_email(email_raw)
    if email is None:
        raise SystemExit("That doesn't look like an email address.")
    user_id = db.create_user(email, auth.hash_password(password), is_admin=is_admin)
    if user_id is None:
        raise SystemExit(f"{email} already has an account.")
    return user_id


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("invite")
    p.add_argument("--email", help="only this address can use the code")
    p.add_argument("--days", type=int, default=7)
    p = sub.add_parser("create-user")
    p.add_argument("email")
    p.add_argument("--admin", action="store_true")
    sub.add_parser("users")
    for name in ("disable", "enable", "make-admin", "reset-password"):
        sub.add_parser(name).add_argument("email")
    p = sub.add_parser("set-limits")
    p.add_argument("email")
    p.add_argument("--videos", help="daily videos, or 'default'")
    p.add_argument("--chats", help="daily chat messages, or 'default'")
    args = parser.parse_args(argv)

    db.init_db()

    if args.cmd == "invite":
        code = auth.new_invite(args.email, args.days)
        print(f"Invite code (valid {args.days} days, single use{', for ' + args.email if args.email else ''}):\n\n    {code}\n")
        print("Copy it now: it can't be shown again.")
    elif args.cmd == "create-user":
        email = auth.normalize_email(args.email) or args.email
        uid = create_user(args.email, _password(email), is_admin=args.admin)
        print(f"Created {'admin ' if args.admin else ''}account #{uid} for {email}.")
    elif args.cmd == "users":
        rows = db.list_users()
        if not rows:
            print("No accounts yet. Create one with: python -m app.admin create-user you@example.com --admin")
        for r in rows:
            u = auth._to_user(r)
            videos, _ = db.usage_in_window(u.id, "video", auth.QUOTA_WINDOW)
            chats, _ = db.usage_in_window(u.id, "chat", auth.QUOTA_WINDOW)
            flags = ", ".join(f for f, on in (("admin", u.is_admin), ("DISABLED", r["disabled"])) if on) or "user"
            lim = lambda v, own: "default" if own is None else str(own)  # noqa: E731
            print(f"#{u.id:<3} {u.email:<34} {flags:<9} videos {videos} (limit {lim(videos, u.video_limit)})  chats {chats} (limit {lim(chats, u.chat_limit)})  joined {r['created_at'][:10]}")
    elif args.cmd in ("disable", "enable"):
        row = _user(args.email)
        db.update_user(row["id"], disabled=int(args.cmd == "disable"))
        if args.cmd == "disable":
            db.delete_user_sessions(row["id"])
        print(f"{row['email']} is now {'disabled' if args.cmd == 'disable' else 'enabled'}.")
    elif args.cmd == "make-admin":
        row = _user(args.email)
        db.update_user(row["id"], is_admin=1)
        print(f"{row['email']} is now an admin.")
    elif args.cmd == "reset-password":
        row = _user(args.email)
        db.update_user(row["id"], password_hash=auth.hash_password(_password(row["email"])))
        db.delete_user_sessions(row["id"])
        print(f"Password changed for {row['email']}; they were signed out everywhere.")
    elif args.cmd == "set-limits":
        row = _user(args.email)
        changes: dict[str, int | None] = {}
        for flag, column in ((args.videos, "video_limit"), (args.chats, "chat_limit")):
            if flag is not None:
                if flag == "default":
                    changes[column] = None
                elif flag.isdigit():
                    changes[column] = int(flag)
                else:
                    raise SystemExit("Limits must be a number or 'default'.")
        if not changes:
            raise SystemExit("Give --videos and/or --chats.")
        db.update_user(row["id"], **changes)
        print(f"Updated limits for {row['email']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
