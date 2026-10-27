import os
import socket

from dotenv import load_dotenv


load_dotenv()

from app import create_app


app = create_app()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _print_routes() -> None:
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        methods = ",".join(sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"}))
        print(f"{rule.rule:<40} {methods:<12} {rule.endpoint}")


def _can_bind(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            bind_host = host if host not in {"0.0.0.0", "::"} else "127.0.0.1"
            sock.bind((bind_host, int(port)))
            return True
        except OSError:
            return False


def _resolve_startup_port(host: str, requested_port: int) -> int:
    fallback_enabled = _env_bool("AUTO_PORT_FALLBACK", True)
    if _can_bind(host, requested_port):
        return requested_port
    if not fallback_enabled:
        raise OSError(f"Port {requested_port} is not available")

    for candidate in range(requested_port + 1, requested_port + 51):
        if _can_bind(host, candidate):
            print(f"[startup] Port {requested_port} is busy. Falling back to {candidate}.")
            return candidate

    raise OSError(
        f"Port {requested_port} is busy and no free fallback port was found in range {requested_port + 1}-{requested_port + 50}"
    )


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    requested_port = int(os.environ.get("PORT", 3000))
    port = _resolve_startup_port(host, requested_port)
    debug = _env_bool("DEBUG", False)

    if _env_bool("SHOW_ROUTES", False):
        _print_routes()

    app.run(host=host, port=port, debug=debug)
