"""The executer for commands (in CMD, for example: pla run proxy)"""

import io
import socket
import struct
from typing import Final, Literal

import click
from rich.console import Console
from rich.theme import Theme

ENCODING: Final[str] = "utf-8"

CONSOLE: Final[Console] = Console(theme=Theme(inherit=False))

HOST: Final[str] = "127.0.0.1"
PORT: Final[int] = 14561
PORT_LIMIT: Final[int] = PORT + 10

PROCESS_TYPES: Final[list[str]] = ["database", "web", "background"]


def find_background_port() -> tuple[int, int]:
    """Attempts to find the port on which the planner background process is running."""
    output = PORT
    while True:
        if output > PORT_LIMIT:
            raise socket.error

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(1)
        if client.connect_ex((HOST, output)) != 0:
            output += 1
            continue

        client.send(b"\x00")
        
        try:
            signature, pid = struct.unpack(">8sI", client.recv(12))
        except:
            client.close()
            output += 1
            continue

        if signature == "plannerB".encode(ENCODING):
            break

        client.close()
        output += 1
        continue

    return output, pid

def send_command(packet_type: int, data: bytes = b"") -> bytes:
    """Sends a command to a background process."""
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(5)
    client.connect((HOST, find_background_port()[0]))
    client.send(struct.pack(">B", packet_type) + data)
    response = b""
    while (chunk := client.recv(1024)) != b"":
        response += chunk

    return response

def read_string(buffer: io.BytesIO) -> str:
    """Reads the string until the end."""
    output = b""
    while (char := buffer.read(1)) != b"\x00":
        output += char
    
    return output.decode(ENCODING)

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """A simple utility for managing simple services"""
    if ctx.invoked_subcommand is not None:
        return
    
    CONSOLE.print(f"A simple utility for managing simple services")
    print("-"*45 + "\n")
    print()
    for name, command in [(k, v) for k, v in cli.commands.items() if not k.startswith("_")]:
        CONSOLE.print(f"   [yellow]{name}[/]{' ' * (20-len(name))}{(command.help or '').lower()}")

    print("\n" + "-"*48)
    CONSOLE.print("Made with ❤️ and 🍵 by [yellow]stngularity[/] for everyone!")

# LIST [BG: 0x11 LIST SERVICES]
# out:  int size, list of [int type, string name, string command, string cwd, string description, bool autorun, int pid]
@cli.command("list")
def list_command() -> None:
    """List of all registered services"""
    services = []

    data = io.BytesIO(send_command(0x11))
    size = struct.unpack(">I", data.read(4))[0]
    while size > 0:
        type = struct.unpack(">B", data.read(1))[0]
        name = read_string(data)
        command = read_string(data)
        cwd = read_string(data)
        description = read_string(data)
        autorun, pid = struct.unpack(">?I", data.read(5))

        services.append({"type": type, "name": name, "command": command, "cwd": cwd,
                         "description": description, "autorun": autorun, "pid": pid})
        
        size -= 1

    if len(services) == 0:
        return CONSOLE.print("[red]err:[/] there are no registered services")

    print("list of services:")
    for service in services:
        color = "[red]" if service["pid"] == 0 else "[green]"
        pid = f" [bright_black]({service['pid']})[/]" if service["pid"] != 0 else ""
        description = service["description"] or "[bright_black italic]no description[/]"
        CONSOLE.print(f"{color}* {service['name']}:[/] {description}{pid}")

# REGISTER [BG: 0x01 REGISTER]
# in:   int type, string name, string command, string cwd, string description, bool autorun
# out:  int result
@cli.command("register")
@click.argument("name", type=str)
@click.argument("command", type=str)
@click.option("--cwd", type=str, default=None, help="working folder of the service")
@click.option("--description", type=str, default=None, help="description of the process")
@click.option("--type", type=click.Choice(PROCESS_TYPES, case_sensitive=False),
              default="background", help="service type")
@click.option("-a", "--autorun", is_flag=True, help="would to run this service together with the system")
def register_command(
    name: str,
    command: str,
    cwd: str | None,
    description: str | None,
    type: Literal["database", "web", "background"],  # 1, 2, 3
    autorun: bool
) -> None:
    """Registers the service using the specified data"""
    data = struct.pack(">B", PROCESS_TYPES.index(type.lower()) + 1)
    data += name.encode(ENCODING) + b"\0"
    data += command.encode(ENCODING) + b"\0"
    data += ("" if cwd is None else cwd).encode(ENCODING) + b"\0"
    data += ("" if description is None else description).encode(ENCODING) + b"\0"
    data += struct.pack(">?", autorun)

    result = send_command(0x01, data)[0]
    if result == 0:
        return CONSOLE.print("[red]err:[/] a service with this name already exists")
    
    if result != 1:
        return CONSOLE.print("[red]err:[/] unknown error")

    CONSOLE.print(f"[blue]info:[/] the [blue]{type.lower()}[/] service [blue]{name}[/] has been registered")
    CONSOLE.print(f"[blue]info:[/] launching with the command [blue]{command}[/]")

    color = "[green]" if autorun else "[red]"
    CONSOLE.print(f"[blue]info:[/] {color}will{'[/]' if autorun else ' not[/]'} start up with the system")

# UNREGISTER [BG: 0x02 UNREGISTER]
# in:   string name
# out:  int result, int pid
@cli.command("unregister")
@click.argument("name", type=str)
def remove_command(name: str) -> None:
    """Unregisters the service with the specified name"""
    response = send_command(0x02, name.encode(ENCODING) + b"\0")
    result, pid = struct.unpack(">BI", response)
    if result == 0:
        return CONSOLE.print("[red]err:[/] there is no utility with this name")
    
    if result == 1:
        CONSOLE.print(f"[blue]info:[/] the service process [bright_black]({pid})[/] has been stopped")
    
    CONSOLE.print(f"[blue]info:[/] the service has been successfully unregistered")

# RUN [BG: 0x12 RUN SERVICE]
# in:   string name
# out:  int result, int pid
@cli.command("run")
@click.argument("name", type=str)
def run_command(name: str) -> None:
    """Starts the service with the specified name"""
    response = send_command(0x12, name.encode(ENCODING) + b"\0")
    result, pid = struct.unpack(">BI", response)
    if result == 0:
        return CONSOLE.print("[red]err:[/] there is no service with that name")
    
    if result == 1:
        return CONSOLE.print(f"[red]err:[/] the service is already running on [red]{pid} pid[/]")

    if result != 2:
        return CONSOLE.print("[red]err:[/] unknown error")

    CONSOLE.print(f"[blue]info:[/] the service has been successfully started on [blue]{pid} pid[/]")

# STOP [BG: 0x13 STOP SERVICE]
# in:   string name
# out:  int result, int pid
@cli.command("stop")
@click.argument("name", type=str)
def stop_command(name: str) -> None:
    """Stops the service with the specified name"""
    response = send_command(0x13, name.encode(ENCODING) + b"\0")
    result, pid = struct.unpack(">BI", response)
    if result == 0:
        return CONSOLE.print("[red]err:[/] there is no service with that name")

    if result == 1:
        return CONSOLE.print(f"[red]err:[/] the service hasn't been launched yet")

    if result != 2:
        return CONSOLE.print("[red]err:[/] unknown error")

    CONSOLE.print(f"[blue]info:[/] the service has been successfully stopped [bright_black]({pid} pid)[/]")

# RESTART [BG: 0x14 RESTART SERVICE]
# in:   string name
# out:  int result, int oldPid, int newPid
@cli.command("restart")
@click.argument("name", type=str)
def restart_command(name: str) -> None:
    """Restarts the utility with the specified name"""
    response = send_command(0x14, name.encode(ENCODING) + b"\0")
    result, pid1, pid2 = struct.unpack(">BII", response)
    if result == 0:
        return CONSOLE.print("[red]err:[/] there is no service with that name")

    if result == 1:
        return CONSOLE.print(f"[red]err:[/] the service isn't running")

    if result != 2:
        return CONSOLE.print("[red]err:[/] unknown error")
    
    CONSOLE.print(f"[blue]info:[/] the service has been successfully restarted [bright_black]({pid1} -> {pid2})[/]")

# GET [BG: 0x10 GET SERVICE]
# out:   int result, 
@cli.command("inspect")
@click.argument("name", type=str, default=None, metavar="[service]")
def inspect_command(name: str | None) -> None:
    """Checks the status of the utility's background process or the specified service"""
    if name is None:
        try:
            port, pid = find_background_port()
        except socket.error:
            port = None
            pid = None
        
        status = "online" if pid is not None else "offline"
        length = 80

        print()
        CONSOLE.print(f"  [yellow]background process inspection results[/]")
        CONSOLE.print(f"  [yellow]{'-'*(length)}[/]")
        CONSOLE.print(f"  [yellow]status {'.'*(length-len(status)-8)}[/] {status}")
        CONSOLE.print(f"  [yellow]pid {'.'*(length-len(str(pid))-5)}[/] {str(pid).lower()}")
        CONSOLE.print(f"  [yellow]port {'.'*(length-len(str(port))-6)}[/] {str(port).lower()}")
        print()
        
        return

    response = send_command(0x10, name.encode(ENCODING) + b"\0")
    if response[0] == 0:
        return CONSOLE.print("[red]err:[/] there is no service with that name")

    data = io.BytesIO(response)
    rtype = struct.unpack(">B", data.read(1))[0]
    type = PROCESS_TYPES[rtype-1]
    name = read_string(data)
    command = read_string(data)
    cwd = read_string(data) or "[bright_black italic]no cwd[/]"
    description = read_string(data) or "[bright_black italic]no description[/]"
    rautorun, pid = struct.unpack(">?I", data.read(5))
    autorun = "yes" if rautorun else "no"

    length = max(max([len(x) for x in [type, name, command, cwd, description]])+24, 80)

    print()
    CONSOLE.print(f"  [yellow]service inspection results[/]")
    CONSOLE.print(f"  [yellow]{'-'*(length)}[/]")
    CONSOLE.print(f"  [yellow]type {'.'*(length-len(type)-6)}[/] {type}")
    CONSOLE.print(f"  [yellow]name {'.'*(length-len(name)-6)}[/] {name}")
    CONSOLE.print(f"  [yellow]description {'.'*(length-len(description)-13)}[/] {description}")
    CONSOLE.print(f"  [yellow]working directory {'.'*(length-len(cwd)-19)}[/] {cwd}")
    CONSOLE.print(f"  [yellow]run command {'.'*(length-len(command)-13)}[/] {command}")
    CONSOLE.print(f"  [yellow]autorun {'.'*(length-len(autorun)-9)}[/] {autorun}")
    if pid != 0:
        print()
        CONSOLE.print(f"  currently running on [yellow]{pid} pid[/]")

    print()

if __name__ == "__main__":
    try:
        cli()
    except socket.error:
        CONSOLE.print("[red]err:[/] unable to find the background process!")
