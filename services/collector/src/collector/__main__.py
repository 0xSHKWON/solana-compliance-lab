from engine_common.cli import run
from . import Collector, __version__


def main():
    return run("collector", __version__, "/internal/v1/collect", Collector, "collect", 8000)


if __name__ == "__main__":
    raise SystemExit(main())
