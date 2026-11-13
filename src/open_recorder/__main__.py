"""open-recorder                    the editor: start screen, projects, timeline, AI
open-recorder --record           the recorder bar alone, saving to the folder chosen on first launch
open-recorder --check | --shortcut | --selftest | --version"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> int:
    if sys.stdout is None:  # started with pythonw: there is no console to print to
        sys.stdout = sys.stderr = open(os.devnull, "w")

    from . import APP_NAME, __version__
    p = argparse.ArgumentParser(prog="open-recorder",
                                description=f"{APP_NAME}: screen + webcam recorder and editor for Windows.")
    p.add_argument("--record", action="store_true", help="open only the recorder bar, without the editor")
    p.add_argument("--output", metavar="DIR", help="with --record: save recordings in this folder this time")
    p.add_argument("--linked", action="store_true", help=argparse.SUPPRESS)  # started by the editor
    p.add_argument("--check", action="store_true", help="check ffmpeg, the encoder, cameras, mics and screens, then exit")
    p.add_argument("--shortcut", action="store_true", help="put an Open Recorder shortcut on the Desktop, then exit")
    p.add_argument("--selftest", action="store_true",
                   help="record, pause, resume, pause, resume and stop by itself (about 25 s), then exit")
    p.add_argument("--config", metavar="PATH", help="use this settings file instead of the default one")
    p.add_argument("--visible", action="store_true",
                   help="don't hide the bar and bubble from capture (to take a screenshot of the recorder)")
    p.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)  # the editor's web inspector
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = p.parse_args(argv)

    from .win32 import set_dpi_aware
    set_dpi_aware()  # before any window or screenshot
    from .config import LOG_DIR
    from .logs import log, setup
    setup(LOG_DIR, console=args.check or args.selftest)

    if args.check:
        from .check import run_checks
        return run_checks(args.config)
    if args.shortcut:
        from .shortcut import create_shortcut
        path = create_shortcut()
        print(f"Shortcut created: {path}" if path else "Could not create the shortcut.")
        return 0 if path else 1
    if args.record or args.selftest or args.output or args.linked:
        from .recorder.app import run
        return run(args.config, selftest=args.selftest, visible=args.visible, output=args.output, linked=args.linked)
    try:
        from .editor.window import run_editor
    except ImportError as e:  # the editor's window library is missing: still let people record
        log.error(f"EDITOR could not start ({e!r}), opening the recorder instead")
        from .recorder.app import run
        return run(args.config, visible=args.visible)
    return run_editor(args.config, debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())
