"""The executer for commands (in CMD, for example: pla run proxy)"""

import os
import socket
import struct
import ctypes

import click

from general import *

PORT_WAIR_TIMEOUT: int = 1  # in seconds

PROCESS_TYPES: list[str] = ["database", "net", "background"]

#region enable colors in terminal (Windows)
if os.name == "nt":
    hStdOut = ctypes.windll.kernel32.GetStdHandle(-11)
    dwMode = ctypes.c_uint32()
    ctypes.windll.kernel32.GetConsoleMode(hStdOut, ctypes.byref(dwMode))
    ctypes.windll.kernel32.SetConsoleMode(hStdOut, dwMode.value | 0x0004)
#endregion

R: str = "\x1B[0m"


def find_background_port() -> tuple[int, int]:
    """Attempts to find the port on which the planner background process is running."""
    output = PORT
    while True:
        if output > PORT + PORT_OFFSET_LIMIT:
            raise socket.error

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(PORT_WAIR_TIMEOUT)
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

def send_command(packet_type: int, data: bytes = b"") -> Buffer:
    """Sends a command to a background process."""
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(5)
    client.connect((HOST, find_background_port()[0]))
    client.send(struct.pack(">B", packet_type) + data)
    response = b""
    while (chunk := client.recv(1024)) != b"":
        response += chunk

    return Buffer(response)

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """A simple utility for managing simple services"""
    if ctx.invoked_subcommand is not None:
        return
    
    print(f"A simple utility for managing simple services\n{'-'*45}\n")
    for name, command in [(k, v) for k, v in cli.commands.items() if not k.startswith("_")]:
        print(f"   \x1B[33m{name}{R}{' ' * (20-len(name))}{(command.help or '').lower()}")

    print(f"\n{'-'*48}\nMade with ❤️ and 🍵 by \x1B[33mstngularity{R} for everyone!")

# LIST [BG: 0x11 LIST SERVICES]
# out:  int size, list of [int type, string name, string command, string cwd, string description, bool autorun, int pid]
@cli.command("list")
def list_command() -> None:
    """List of all registered services"""
    desc_placeholder = f"\x1B[3;90mno description{R}"

    data = send_command(0x11)
    size = struct.unpack(">I", data.read(4))[0]
    if size == 0:
        return print(f"\x1B[31merr:{R} there are no registered services")

    print("list of services:")
    while size > 0:
        data.skip(1)
        name = data.read_string()
        data.skip_string()
        data.skip_string()
        description = data.read_string()
        _, pid = struct.unpack(">?I", data.read(5))
        
        color = "\x1B[31m" if pid == 0 else "\x1B[32m"
        pid = f" \x1B[90m({pid}){R}" if pid != 0 else ""
        print(f"{color}* {name}:{R} {description or desc_placeholder}{pid}")
        
        size -= 1

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
    type: str,
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
        return print(f"\x1B[31merr:{R} a service with this name already exists")
    
    if result != 1:
        return print(f"\x1B[31merr:{R} unknown error")

    print(f"\x1B[34minfo:{R} the \x1B[34m{type.lower()}{R} service \x1B[34m{name}{R} has been registered")
    print(f"\x1B[34minfo:{R} launching with the command \x1B[34m{command}{R}")

    color = "\x1B[32m" if autorun else "\x1B[31m"
    print(f"\x1B[34minfo:{R} {color}will{R if autorun else ' not' + R} start up with the system")

# UNREGISTER [BG: 0x02 UNREGISTER]
# in:   string name
# out:  int result, int pid
@cli.command("unregister")
@click.argument("name", type=str)
def remove_command(name: str) -> None:
    """Unregisters the service with the specified name"""
    response = send_command(0x02, name.encode(ENCODING) + b"\0").read(5)
    result, pid = struct.unpack(">BI", response)
    if result == 0:
        return print(f"\x1B[31merr:{R} there is no utility with this name")
    
    if result == 1:
        print(f"\x1B[34minfo:{R} the service process \x1B[90m({pid}){R} has been stopped")
    
    print(f"\x1B[34minfo:{R} the service has been successfully unregistered")

# RUN [BG: 0x12 RUN SERVICE]
# in:   string name
# out:  int result, int pid
@cli.command("run")
@click.argument("name", type=str)
def run_command(name: str) -> None:
    """Starts the service with the specified name"""
    response = send_command(0x12, name.encode(ENCODING) + b"\0").read(5)
    result, pid = struct.unpack(">BI", response)
    if result == 0:
        return print(f"\x1B[31merr:{R} there is no service with that name")
    
    if result == 1:
        return print(f"\x1B[31merr:{R} the service is already running on \x1B[31m{pid} pid{R}")

    if result != 2:
        return print(f"\x1B[31merr:{R} unknown error")

    print(f"\x1B[34minfo:{R} the service has been successfully started on \x1B[34m{pid} pid{R}")

# STOP [BG: 0x13 STOP SERVICE]
# in:   string name
# out:  int result, int pid
@cli.command("stop")
@click.argument("name", type=str)
def stop_command(name: str) -> None:
    """Stops the service with the specified name"""
    response = send_command(0x13, name.encode(ENCODING) + b"\0").read(5)
    result, pid = struct.unpack(">BI", response)
    if result == 0:
        return print(f"\x1B[31merr:{R} there is no service with that name")

    if result == 1:
        return print(f"\x1B[31merr:{R} the service hasn't been launched yet")

    if result != 2:
        return print(f"\x1B[31merr:{R} unknown error")

    print(f"\x1B[34minfo:{R} the service has been successfully stopped \x1B[90m({pid} pid){R}")

# RESTART [BG: 0x14 RESTART SERVICE]
# in:   string name
# out:  int result, int oldPid, int newPid
@cli.command("restart")
@click.argument("name", type=str)
def restart_command(name: str) -> None:
    """Restarts the utility with the specified name"""
    response = send_command(0x14, name.encode(ENCODING) + b"\0").read(9)
    result, pid1, pid2 = struct.unpack(">BII", response)
    if result == 0:
        return print(f"\x1B[31merr:{R} there is no service with that name")

    if result == 1:
        return print(f"\x1B[31merr:{R} the service isn't running")

    if result != 2:
        return print(f"\x1B[31merr:{R} unknown error")
    
    print(f"\x1B[34minfo:{R} the service has been successfully restarted \x1B[90m({pid1} -> {pid2}){R}")

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
        print(f"  \x1B[33mbackground process inspection results{R}")
        print(f"  \x1B[33m{'-'*(length)}{R}")
        print(f"  \x1B[33mstatus {'.'*(length-len(status)-8)}{R} {status}")
        print(f"  \x1B[33mpid {'.'*(length-len(str(pid))-5)}{R} {str(pid).lower()}")
        print(f"  \x1B[33mport {'.'*(length-len(str(port))-6)}{R} {str(port).lower()}")
        print()
        
        return

    response = send_command(0x10, name.encode(ENCODING) + b"\0")
    if response[0] == 0:
        return print(f"\x1B[31merr:{R} there is no service with that name")

    rtype = struct.unpack(">B", response.read(1))[0]
    type = PROCESS_TYPES[rtype-1]

    name = response.read_string()
    command = response.read_string()
    cwd = response.read_string() or f"\x1B[3;90mno cwd{R}"
    description = response.read_string() or f"\x1B[3;90mno description{R}"
    rautorun, pid = struct.unpack(">?I", response.read(5))
    autorun = "yes" if rautorun else "no"

    length = max([len(type), len(name), len(command), len(cwd), len(description), 56])+24

    print()
    print(f"  \x1B[33mservice inspection results{R}")
    print(f"  \x1B[33m{'-'*(length)}{R}")
    print(f"  \x1B[33mtype {'.'*(length-len(type)-6)}{R} {type}")
    print(f"  \x1B[33mname {'.'*(length-len(name)-6)}{R} {name}")
    print(f"  \x1B[33mdescription {'.'*(length-len(description)-13)}{R} {description}")
    print(f"  \x1B[33mworking directory {'.'*(length-len(cwd)-19)}{R} {cwd}")
    print(f"  \x1B[33mrun command {'.'*(length-len(command)-13)}{R} {command}")
    print(f"  \x1B[33mautorun {'.'*(length-len(autorun)-9)}{R} {autorun}")
    if pid != 0:
        print(f"\n  currently running on \x1B[33m{pid} pid{R}")

    print()

if __name__ == "__main__":
    try:
        cli()
    except socket.error:
        print(f"\x1B[31merr:{R} unable to find the background process!")
