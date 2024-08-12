from typing import Optional

import click

from jumpstarter.config import (
    ClientConfigV1Alpha1,
    ClientConfigV1Alpha1Client,
    ClientConfigV1Alpha1Drivers,
    UserConfigV1Alpha1,
)

from .util import AliasedGroup, make_table


@click.group(cls=AliasedGroup, short_help="Manage and interact with clients.")
def client():
    pass


@click.command("create", short_help="Create a client configuration.")
@click.argument("name")
@click.option(
    "-o",
    "--out",
    type=click.Path(dir_okay=False, resolve_path=True, writable=True),
    help="Specify an output file for the client config.",
)
@click.option(
    "-e",
    "--endpoint",
    type=str,
    help="Enter the Jumpstarter service endpoint.",
    prompt="Enter a valid Jumpstarter service endpoint",
)
@click.option(
    "-t",
    "--token",
    type=str,
    help="A valid Jumpstarter auth token generated by the Jumpstarter service.",
    prompt="Enter a Jumpstarter auth token (hidden)",
    hide_input=True,
)
@click.option(
    "-a",
    "--allow",
    type=str,
    help="A comma-separated list of driver client packages to load.",
    prompt="Enter a comma-separated list of allowed driver packages (optional)",
    default="",
)
@click.option("--unsafe", is_flag=True, help="Should all driver client packages be allowed to load (UNSAFE!).")
def client_create(
    name: str,
    endpoint: str,
    token: str,
    allow: str,
    unsafe: bool,
    out: Optional[str],
):
    """Create a Jumpstarter client configuration."""
    if out is None and ClientConfigV1Alpha1.exists(name):
        raise click.ClickException(f"A client with the name '{name}' already exists.")

    config = ClientConfigV1Alpha1(
        name=name,
        client=ClientConfigV1Alpha1Client(
            endpoint=endpoint, token=token, drivers=ClientConfigV1Alpha1Drivers(allow=allow.split(","), unsafe=unsafe)
        ),
    )
    ClientConfigV1Alpha1.save(config, out)

    # If this is the only client config, set it as default
    if out is None and len(ClientConfigV1Alpha1.list()) == 1:
        user_config = UserConfigV1Alpha1.load_or_create()
        user_config.config.current_client = config
        UserConfigV1Alpha1.save(user_config)


def set_next_client(name: str):
    user_config = UserConfigV1Alpha1.load() if UserConfigV1Alpha1.exists() else None
    if (
        user_config is not None
        and user_config.config.current_client is not None
        and user_config.config.current_client.name == name
    ):
        for c in ClientConfigV1Alpha1.list():
            if c.name != name:
                # Use the next available client config
                user_config.use_client(c.name)
                return
        # Otherwise, set client to none
        user_config.use_client(None)


@click.command("delete", short_help="Delete a client configuration.")
@click.argument("name", type=str)
def client_delete(name: str):
    """Delete a Jumpstarter client configuration."""
    set_next_client(name)
    ClientConfigV1Alpha1.delete(name)


@click.command("list", short_help="List available client configurations.")
def client_list():
    # Allow listing if there is no user config defined
    current_name = None
    if UserConfigV1Alpha1.exists():
        current_client = UserConfigV1Alpha1.load().config.current_client
        current_name = current_client.name if current_client is not None else None

    configs = ClientConfigV1Alpha1.list()

    columns = ["CURRENT", "NAME", "ENDPOINT", "PATH"]

    def make_row(c: ClientConfigV1Alpha1):
        return {
            "CURRENT": "*" if current_name == c.name else "",
            "NAME": c.name,
            "ENDPOINT": c.client.endpoint,
            "PATH": str(c.path),
        }

    rows = list(map(make_row, configs))
    click.echo(make_table(columns, rows))


@click.command("use", short_help="Select the current client configuration.")
@click.argument("name", type=str)
def client_use(name: str):
    """Select the current Jumpstarter client configuration to use."""
    user_config = UserConfigV1Alpha1.load_or_create()
    user_config.use_client(name)


client.add_command(client_create)
client.add_command(client_delete)
client.add_command(client_list)
client.add_command(client_use)
