import unicodedata
from asyncio import run as async_run
from getpass import getpass, getuser
from pathlib import Path
from typing import Annotated

import typer
from rich import print as colored_print
from sqlalchemy import inspect
from sqlalchemy.exc import NoInspectionAvailable

from fastdaisy_admin import __version__
from fastdaisy_admin.auth.discover import get_admin_data
from fastdaisy_admin.exceptions import FastDaisyAdminException, InvalidModelError

app = typer.Typer()


def version_callback(value: bool) -> None:
    if value:
        colored_print(f"[blue]Fastdaisy-admin[/blue] version: [green]{__version__}[/green]")
        raise typer.Exit()


@app.callback()
def callback(
    version: Annotated[
        bool | None,
        typer.Option("--version", help="Show the version", callback=version_callback),
    ] = None,
) -> None:
    """
    FastDaisy-Admin - The [bold]fastapi[/bold] Admin made with DaisyUI
    """
    ...


def get_default_username() -> str:
    default_username = getuser()
    try:
        default_username = (
            unicodedata.normalize("NFKD", default_username)
            .encode("ascii", "ignore")
            .decode("ascii")
            .replace(" ", "")
            .lower()
        )
    except UnicodeDecodeError:
        return ""
    return default_username


@app.command()
def createsuperuser(
    path: Annotated[
        Path | None,
        typer.Argument(
            help="A path to a Python file or package directory (with [blue]__init__.py[/blue] files) containing a [bold]Admin[/bold]."
        ),
    ] = None,
):
    admindata = get_admin_data(path=path)
    if not admindata.authentication:
        raise FastDaisyAdminException(
            "Cannot create a 'superuser' because authentication is disabled. "
            "Set `authentication=True` when initializing the Admin class."
        )

    auth_model = admindata.auth_model
    try:
        mapper = inspect(auth_model)
    except NoInspectionAvailable:
        name = auth_model.__name__ if hasattr(auth_model, "__name__") else auth_model
        raise InvalidModelError(f"{name} is not a SQLAlchemy model.")

    async_run(admindata.initialize_admin_db())
    user_data: dict[str, str] = {}
    authservice = admindata.auth_service

    while not user_data.get("username"):
        username: str | None
        default_username = get_default_username()
        title = f"Username (leave blank to use '{default_username}'): "
        username = input(title).strip() or default_username
        try:
            async_run(authservice.validate_username(username, mapper))
        except ValueError as e:
            typer.secho(f"Error: {e}", fg=typer.colors.RED)
            username = None

        if username:
            user_data["username"] = username

    while not user_data.get("password"):
        password = getpass("Password: ")
        confirm_password = getpass("Confirm Password: ")
        if password != confirm_password:
            typer.secho("Error: Passwords do not match. Try again.\n", fg=typer.colors.RED)
            continue
        try:
            authservice.validate_password(password, mapper)
        except ValueError as e:
            typer.secho(f"Error: {e}", fg=typer.colors.RED)
            response = input("Bypass password validation and create user anyway? [y/N]: ")
            if response.lower() != "y":
                continue

        user_data["password"] = password

    async_run(authservice.create_superuser(username, password))
    typer.secho(f"\nSuperuser '{username}' created successfully!", fg=typer.colors.GREEN)
