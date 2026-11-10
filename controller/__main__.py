"""CLI entry point: python -m controller --url URL --db PATH."""

import argparse
import os

from .api import Api
from .loop import Controller
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--db", default=os.environ.get("CONTROLLER_DB", "runs/controller.sqlite"))
    args = parser.parse_args()
    api = Api(args.url)
    try:
        with Store(args.db) as store:
            Controller(api, store).run()
    finally:
        api.close()


if __name__ == "__main__":
    main()
