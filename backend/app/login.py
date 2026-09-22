"""Sign in once, by hand, into the profile the fetchers reuse.

    ./.venv/bin/python -m app.login                      # douyin
    ./.venv/bin/python -m app.login --platform tiktok

Opens a browser at the site and waits. Sign in however you
normally would -- the code is never read, typed or stored here; what
persists is the session the site itself writes into the profile
directory, exactly as it would in an ordinary browser.

Run it again whenever a fetch run reports a login wall: sessions
expire, and this is how they are renewed.

Each platform has its own profile directory, so signing in to one
never disturbs the other and a session blocked on one costs only that
platform's collection. Both sites are the same company's and set
cookies of the same names, which is exactly why the check is scoped
to the site's own domain.

`--profile DIR` keeps separate accounts apart. A research account,
used for nothing else, keeps this collection off a personal one --
worth doing in a study of what a platform removes from a community
it polices, and easier to describe in an ethics application.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .browser import HOMES, PROFILES, open_browser, signed_in


def main() -> None:  # pragma: no cover - interactive by nature
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform", default="douyin", choices=sorted(PROFILES),
        help="which site to sign in to",
    )
    parser.add_argument(
        "--profile",
        default="",
        help="profile directory; defaults to one per platform",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the saved session still opens the site",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "wait for a sign-in even if this profile looks signed in "
            "already -- use when the check is wrong"
        ),
    )
    parser.add_argument(
        "--show-cookies",
        action="store_true",
        help=(
            "list the cookie names and domains in this profile, never "
            "their values, to check what a sign-in actually sets"
        ),
    )
    args = parser.parse_args()
    profile = Path(args.profile) if args.profile else PROFILES[args.platform]
    home = HOMES[args.platform]
    site = args.platform

    if args.show_cookies:
        with open_browser(profile, headless=True, platform=site) as browser:
            browser.read(home, settle_seconds=2.0)
            print(f"{profile}:")
            for name, domain in browser.cookie_names():
                print(f"  {name:<28} {domain}")
            known = browser.session_cookies()
            print(
                f"\n  read as a session: {', '.join(known) if known else 'none'}"
            )
        return

    if args.check:
        with open_browser(profile, headless=True, platform=site) as browser:
            # Cookies for a domain reach the jar only once something
            # from it has loaded.
            browser.read(home, settle_seconds=1.0)
            if signed_in(browser):
                print(f"{profile}: the session still opens {site}")
            else:
                print(
                    f"{profile}: the site is asking to sign in.\n"
                    "Run this without --check and sign in by hand."
                )
        return

    with open_browser(profile, headless=False, platform=site) as browser:
        browser.read(home, settle_seconds=1.0)
        if browser.is_signed_in() and not args.force:
            found = ", ".join(browser.session_cookies())
            print(
                f"Already signed in; {profile}/ holds a session ({found}).\n"
                "If the site is in fact asking you to sign in, re-run with "
                "--force and this will wait anyway."
            )
            return

        print(
            f"\nA browser window is open at {home}\n"
            "Sign in there however you normally would -- scan the code, or\n"
            "take the SMS route. Nothing is typed or read by this program.\n"
            "The window stays open until the sign-in lands: no keypress here\n"
            "will close it, so there is no way to cut yourself off halfway."
        )
        if browser.wait_until_signed_in():
            print(f"\nSigned in. The session is saved in {profile}/")
            print(
                "Now: ./.venv/bin/python -m app.fetch_videos "
                f"--platform {site} --apply --limit 5"
            )
        else:
            print(
                "\nNo session appeared before the wait ran out, so nothing "
                "was saved that a fetch run could use. Run this again."
            )


if __name__ == "__main__":  # pragma: no cover
    main()
