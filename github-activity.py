#!/usr/bin/python3

import argparse
import curses
import functools
import json
import os
import subprocess
import sys
import threading
import time
from curses import wrapper
from dataclasses import dataclass
from datetime import datetime
from select import select
from typing import List

from github import Github

DEFAULT_CONFIG_PATH = "~/.config/sextens/config.json"


def timed_cache(seconds: int):
    def _wrapper(f):
        expired_at = -1
        cached_res = None

        @functools.wraps(f)
        def _wrapped(*args, **kwargs):
            nonlocal expired_at
            nonlocal cached_res

            now = time.time()
            if now >= expired_at:
                res = f(*args, **kwargs)
                cached_res = res
                expired_at = now + seconds
            else:
                res = cached_res
            return res

        return _wrapped

    return _wrapper


@dataclass
class StarEvent:
    username: str
    repo_name: str
    repo_fullname: str
    repo_url: str
    repo_desc: str
    created_at: datetime


# TODO: use async way to feed data to buffer
class StarEventGather:
    def __init__(self, client: Github):
        self._cli = client

    def get_star_list(self, username: str) -> List[StarEvent]:
        user = self._cli.get_user(username)
        events = user.get_received_events()[:100]

        results = []
        for event in events:
            if (
                event.type not in ("WatchEvent")
                and event.payload.get("action") != "started"
            ):
                continue
            results.append(
                StarEvent(
                    username=event.actor.name,
                    repo_name=event.repo.name.split("/")[-1],
                    repo_fullname=event.repo.name,
                    repo_desc=event.repo.description or "",
                    repo_url=event.repo.html_url or "",
                    created_at=event.created_at,
                )
            )

        return results


@timed_cache(seconds=120)
def list_start_events_by_username(
    client: Github, username: str
) -> List[StarEvent]:
    gather = StarEventGather(client)
    events = gather.get_star_list(username)
    return events


class App:
    _token: str
    _username: str

    def __init__(self, config_path: str):
        self.ev = threading.Event()
        self.config_path = config_path
        self.load_config()

    def _pregetcher(self):
        # because curses.getch doesn't work well with threads
        while True:
            select([sys.stdin], [], [], 10)
            self.ev.set()

    def load_config(self):
        data = {}
        with open(self.config_path, "r") as f:
            data = json.loads(f.read())

        self._token = data.get("token", "")
        self._username = data.get("username", "")

    def _init_term_color(self):
        # Start colors in curses
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)

    def run(self, stdscr):
        client = Github(self._token)

        threading.Thread(target=self._pregetcher, daemon=True).start()

        k = 0
        cursor_x = 0
        cursor_y = 0

        # Clear and refresh the screen for a blank canvas
        stdscr.clear()
        stdscr.refresh()

        self._init_term_color()

        history = {}
        while k != ord("q"):
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            if k == ord("j"):
                cursor_y = cursor_y + 1
            elif k == ord("k"):
                cursor_y = cursor_y - 1
            cursor_y = min(height - 1, cursor_y, len(history) - 1)
            cursor_y = max(0, cursor_y)

            # https://stackoverflow.com/questions/11067800/ncurses-key-enter-is-fail
            if k == ord("o"):
                # open repo url if exists
                record = history.get(cursor_y)
                if record is not None:
                    subprocess.run(
                        f"xdg-open {record.repo_url}",
                        shell=True,
                        encoding="utf-8",
                    )

            # whstr = "Width: {}, Height: {}".format(width, height)
            records = list_start_events_by_username(client, self._username)
            for row, record in enumerate(records):
                history[row] = record
                created_at = record.created_at.strftime("%Y-%d %H:%M")
                s = (
                    f"{created_at}: {record.username:<16} "
                    f"starred {record.repo_name:<24}"
                )
                if len(record.repo_desc) > 40:
                    s += f" {{{record.repo_desc[:40]}...}}"
                elif len(record.repo_desc) > 0:
                    s += f" {{{record.repo_desc[:40]}}}"

                if row == cursor_y:
                    stdscr.addstr(
                        row,
                        0,
                        s,
                        curses.color_pair(1) | curses.A_BOLD,
                    )
                else:
                    stdscr.addstr(row, 0, s, curses.color_pair(1))

            stdscr.addstr(
                height - 1, 0, "Use j/k to move cursor and o to open link"
            )

            stdscr.move(cursor_y, cursor_x)
            stdscr.refresh()

            self.ev.wait()
            self.ev.clear()

            k = stdscr.getch()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="")
    parser.add_argument(
        "--config",
        action="store",
        dest="config_path",
        type=str,
        help="config path",
        default=DEFAULT_CONFIG_PATH,
    )
    args = parser.parse_args()
    config_path = os.path.expanduser(args.config_path)

    if not os.path.exists(config_path):
        print("Err: your config is not existed, please check config")

    wrapper(App(config_path=config_path).run)
