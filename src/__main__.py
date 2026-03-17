"""The executer for commands (in CMD, for example: pla run proxy)"""

import os
import re
import sys
import socket
import struct
import ctypes
from typing import Any

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

def help_command() -> None:
    """A simple utility for managing simple services"""
    print(f"a simple utility for managing simple services\n{'-'*45}\n")
    for name, command in [(k, v) for k, v in commands.items() if not k.startswith("_")]:
        description = command.get("description", command["handler"].__doc__).lower()
        print(f"   \x1B[33m{name}{R}{' ' * (20-len(name))}{description}")

    print(f"\n{'-'*48}\nmade with ❤️ and 🍵 by \x1B[33mstngularity{R} for everyone!")

# LIST [BG: 0x11 LIST SERVICES]
# out:  int size, list of [int type, string name, string command, string cwd, string description, bool autorun, int pid]
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
def unregister_command(name: str) -> None:
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


commands = {
    "help": {
        "description": "Reference for all planner commands",
        "handler": help_command
    },
    "list": {
        "handler": list_command
    },
    "register": {
        "handler": register_command,
        "arguments": [
            ("name", str, "service name (also known as the service id)"),  # name, type, description, default?
            ("command", str, "the command that starts the service")
        ],
        "options": [
            ("cwd", str, "working folder of the service"),  # name, type, description, default? (None by default)
            ("description", str, "description of the process"),
            ("type", PROCESS_TYPES, "service type", "background")  # type may be list of possible values
        ],
        "flags": [
            ("autorun", ["a"], "would to run this service together with the system")  # name, aliases, description, default? (False by default)
        ]
    },
    "unregister": {
        "handler": unregister_command,
        "arguments": [("name", str, "service name (also known as the service id)")]
    },
    "run": {
        "handler": run_command,
        "arguments": [("name", str, "service name (also known as the service id)")]
    },
    "stop": {
        "handler": stop_command,
        "arguments": [("name", str, "service name (also known as the service id)")]
    },
    "restart": {
        "handler": restart_command,
        "arguments": [("name", str, "service name (also known as the service id)")]
    },
    "inspect": {
        "handler": inspect_command,
        "arguments": [("name", str, "service name (also known as the service id)", None)]
    }
}

type_name_map = {
    str: "string",
    int: "integer",
    bool: "boolean"
}

def build_usage(command: str) -> str:
    """:class:`str`: Builds usage line for the specified command."""
    cmd_obj = commands[command]
    arguments = (""
                 if (args := cmd_obj.get("arguments")) is None 
                 else " " + " ".join(f"<{x[0]}>" if len(x) == 3 else f"[{x[0]}]" for x in args))
    
    return f"{sys.argv[0]} {command}{arguments}"

def parse_bool(value: str) -> bool:
    """:class:`bool`: Attempts to convert the specified value to a boolean."""
    if value.lower() in ["true", "yes", "y"]:
        return True
    
    if value.lower() in ["false", "no", "n"]:
        return False
    
    raise ValueError

def parse_value(value: str, type: type[Any] | Any, name: str) -> Any:
    """Attempting to process the value of the argument/option."""
    if isinstance(type, list) and (value.lower() not in type):
        return print(f"\x1B[31merr:{R} possible values for \x1B[31m{name}:{R} {', '.join(type)}")
    
    if isinstance(type, list):
        return value.lower()

    try:
        typed_value = parse_bool(value) if issubclass(type, bool) else type(value)
        return typed_value
    except ValueError:
        type_name = type_name_map.get(type, type.__qualname__)
        return print(f"\x1B[31merr:{R} {name} must be {type_name}")

def main() -> None:
    """CLI entry point. Processes all arguments and executes the appropriate commands."""
    command = sys.argv[1:]
    if (len(command) == 0) or ("-h" in command) or ("--help" in command):
        return commands["help"]["handler"]()
    
    if command[0] not in commands:
        return print(f"\x1B[31merr:{R} unknown command: {command[0]}")
    
    cmd_obj = commands[command[0]]
    kwargs = {}

    values = command[1:]
    options = cmd_obj.get("options", [])
    for option in options:
        string = f"--{option[0]}"
        if string not in values:
            continue

        index = values.index(string)
        if index == len(values)-1:
            return print(f"\x1B[31merr:{R} the value of the \x1B[31m{option[0]}{R} option is missing")

        value = values[index+1]
        if value.startswith("-"):
            return print(f"\x1B[31merr:{R} the value of the \x1B[31m{option[0]}{R} option is missing")
        
        parsed_value = parse_value(re.sub(r"(?<!\\)\\", "", value), option[1], option[0])
        if value is None:
            return
        
        kwargs[option[0]] = parsed_value
        values.pop(index+1)
        values.pop(index)
    
    for option in [x for x in options if x[0] not in kwargs]:
        kwargs[option[0]] = None if len(option) == 3 else option[3]

    flags = cmd_obj.get("flags", [])
    for flag in flags:
        for name in [f"-{flag[0]}"] + flag[1]:
            string = f"-{name}"
            if string in values:
                kwargs[flag[0]] = True if len(flag) == 3 else not flag[3]
                values.remove(string)
    
    for flag in [x for x in flags if x[0] not in kwargs]:
        kwargs[flag[0]] = False if len(flag) == 3 else flag[3]
    
    if any(map((lambda x: x.startswith("-")), values)):
        unknown = [x for x in values if x.startswith("-")][0]
        return print(f"\x1B[31merr:{R} unknown option or flag: {unknown}")

    arguments = cmd_obj.get("arguments")
    if (arguments is not None) and (len(command) < len([x for x in arguments if len(x) == 3])+1):
        return print(f"\x1B[31merr:{R} usage: {build_usage(command[0])}")

    for i, argument in enumerate(arguments or []):
        try:
            raw_value = values[i]
        except IndexError:
            continue

        value = parse_value(raw_value, argument[1], argument[0])
        if value is None:
            return
        
        kwargs[argument[0]] = value
    
    for argument in [x for x in arguments if x[0] not in kwargs]:
        kwargs[argument[0]] = argument[3]

    cmd_obj["handler"](**kwargs)

if __name__ == "__main__":
    try:
        main()
    except socket.error:
        print(f"\x1B[31merr:{R} unable to find the background process!")
