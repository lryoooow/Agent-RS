import uvicorn

from app.shared.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload,
        reload_excludes=["storage/*", "storage/**/*"],
    )


if __name__ == "__main__":
    main()
