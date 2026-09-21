"""Sign in once, by hand, into the profile the fetchers reuse.

    ./.venv/bin/python -m app.login

Opens a browser at douyin.com and waits. Sign in however you
normally would -- the code is never read, typed or stored here; what
persists is the session the site itself writes into the profile
directory, exactly as it would in an ordinary browser.

Run it again whenever a fetch run reports a login wall: sessions
expire, and this is how they are renewed.

`--profile DIR` keeps separate accounts apart. A research account,
used for nothing else, keeps this collection off a personal one --
worth doing in a study of what a platform removes from a community
it polices, and easier to describe in an ethics application.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .browser import DEFAULT_PROFILE, open_browser, signed_in


def main() -> None:  # pragma: no cover - interactive by nature
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the saved session still opens the site",
    )
    args = parser.parse_args()
    profile = Path(args.profile)

    if args.check:
        with open_browser(profile, headless=True) as browser:
            if signed_in(browser):
                print(f"{profile}: the session still opens douyin.com")
            else:
                print(
                    f"{profile}: the site is asking to sign in.\n"
                    "Run this without --check and sign in by hand."
                )
        return

    with open_browser(profile, headless=False) as browser:
        browser.read("https://www.douyin.com/", settle_seconds=1.0)
        browser.wait_for_person(
            "Sign in to Douyin in the window that opened."
        )
        if signed_in(browser):
            print(f"Signed in. The session is saved in {profile}/")
        else:
            print(
                "The site is still asking to sign in. Nothing was saved that "
                "will let a fetch run through; try again."
            )


if __name__ == "__main__":  # pragma: no cover
    main()
