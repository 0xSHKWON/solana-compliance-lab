from engine_common.cli import run
from . import PolicyEngine, __version__


def main():
    return run("policy-engine", __version__, "/internal/v1/policy/decide", PolicyEngine, "decide", 8002)


if __name__ == "__main__":
    raise SystemExit(main())
