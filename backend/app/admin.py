"""Admin commands for a deployment with accounts (AUTH_ENABLED=true).

Run from backend/:   uv run python -m app.admin <command>

  invite [--email E] [--days 7]     create a one-time invite code (shown once; only its hash is stored)
  create-user EMAIL [--admin]       create an account directly (asks for the password)
  users                             list accounts with today's usage
  disable EMAIL / enable EMAIL      block / unblock a user (also signs them out)
  set-limits EMAIL [--videos N] [--chats N]   per-user daily limits ("default" resets to the server default)
  make-admin EMAIL                  admins have no quotas and can see every job
  reset-password EMAIL              set a new password and sign the user out everywhere
  set-plan EMAIL standard|pro|max   which plan the account is on (what each plan includes: app/features.py)
  set-feature EMAIL KEY VALUE       change ONE feature for ONE account, e.g. studio on / studio_max_height 720
                                    ("default" removes the change and goes back to what the plan says)
  features EMAIL                    show what the account can use, and which values were changed by hand
  light-copies                      make the light playing copies for videos finished before they existed

Passwords are read from a hidden prompt, or from the SEQNCE_ADMIN_PASSWORD environment variable for
scripts. They are never accepted on the command line, so they don't end up in your shell history.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import Sequence

import json

from . import auth, db, features
from .config import get_settings
from .services import playback


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
    p = sub.add_parser("set-plan")
    p.add_argument("email")
    p.add_argument("plan", choices=features.PLAN_NAMES)
    p = sub.add_parser("set-feature")
    p.add_argument("email")
    p.add_argument("key", choices=list(features.FEATURES))
    p.add_argument("value", help="on/off or a number, or 'default' to go back to the plan's value")
    sub.add_parser("features").add_argument("email")
    sub.add_parser("light-copies")
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
            plan = "admin" if u.is_admin else u.plan + ("*" if u.overrides else "")  # * = some features changed by hand
            print(f"#{u.id:<3} {u.email:<34} {flags:<9} {plan:<9} videos {videos} (limit {lim(videos, u.video_limit)})  chats {chats} (limit {lim(chats, u.chat_limit)})  joined {r['created_at'][:10]}")
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
    elif args.cmd == "set-plan":
        row = _user(args.email)
        db.update_user(row["id"], plan=args.plan)
        print(f"{row['email']} is now on the {args.plan} plan.")
        _show_features(db.get_user(row["id"]) or row)
    elif args.cmd == "set-feature":
        row = _user(args.email)
        overrides = features.clean_overrides(json.loads(row["features_json"]) if row.get("features_json") else {})
        if args.value.strip().lower() == "default":
            overrides.pop(args.key, None)
        else:
            try:
                overrides[args.key] = features.parse_value(args.key, args.value)
            except ValueError as exc:
                raise SystemExit(str(exc))
        db.update_user(row["id"], features_json=json.dumps(overrides) if overrides else None)
        print(f"Updated {args.key} for {row['email']}.")
        _show_features(db.get_user(row["id"]) or row)
    elif args.cmd == "features":
        _show_features(_user(args.email))
    elif args.cmd == "light-copies":
        made, looked = make_light_copies()
        print(f"Looked at {looked} finished video(s); made {made} light cop{'y' if made == 1 else 'ies'}.")
    return 0


def make_light_copies() -> tuple[int, int]:
    """Light playing copies (services/playback.py) for every finished video that has none yet. Safe to run again."""
    cfg = get_settings()
    videos = [p for p in cfg.outputs_dir.glob("*.mp4") if not p.name.endswith((".play.mp4", ".partial.mp4"))]
    videos += [p for kind in ("slideshows", "studio") for p in (cfg.storage_dir / kind).glob("*/output.mp4")]
    made = sum(playback.make(v) for v in videos if playback.best(v) == v)
    return made, len(videos)


def _show_features(row: dict) -> None:
    """Print what an account can use now; '*' marks a value changed by hand (differs from the plan)."""
    user = auth._to_user(row)
    if user.is_admin:
        print(f"{user.email} is an admin: everything is on, with no daily Studio limit.")
        return
    values = auth.features_of(user)
    base = features.PLANS.get(user.plan, features.PLANS[features.DEFAULT_PLAN])
    print(f"{user.email}  plan: {user.plan}")
    for key, (_, meaning) in features.FEATURES.items():
        shown = values[key]
        shown = ("on" if shown else "off") if isinstance(shown, bool) else str(shown)
        mark = "*" if key in user.overrides and user.overrides[key] != base[key] else " "
        print(f"  {mark} {key:<24} {shown:<6} {meaning}")


if __name__ == "__main__":
    sys.exit(main())
