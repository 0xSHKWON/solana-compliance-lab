from engine_common.cli import run
from . import Detector, __version__


def main():
    return run("kyt-engine", __version__, "/internal/v1/kyt/evaluate", Detector, "evaluate", 8001)


if __name__ == "__main__":
    raise SystemExit(main())
