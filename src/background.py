"""The background part of `planner`"""

import os
import io
import sys
import time
import shlex
import errno
import signal
import socket
import struct
from pathlib import Path
from threading import Thread
from subprocess import Popen, DEVNULL
from typing import Any, Final, Optional

if os.name == "nt":
    import ctypes

import simdjson

STATE_AUDIT_COOLDOWN: Final[int] = 5  # in seconds
STOP_SERVICE_TIMEOUT: Final[int] = 5  # in seconds
ENCODING: Final[str] = "utf-8"

PROC_FILE: Final[Path] = Path(__file__).parent.parent / "proc"

HOST: Final[str] = "127.0.0.1"
PORT: Final[int] = 14561  # I don't remember why I chose this particular port.
PORT_LIMIT: Final[int] = PORT + 10

popens: dict[str, Popen] = {}  # key - SID (service id); value - popen


def stop_service(sid: str) -> None:
    """Attempts to stop the process with the specified ID."""
    popen = popens[sid]
    popen.__dict__["_kill"] = True
    os.kill(popen.pid, signal.SIGTERM)

    time.sleep(STOP_SERVICE_TIMEOUT)
    if os.name == "nt":
        hProcess = ctypes.windll.kernel32.OpenProcess(0x0001, False, popen.pid)
        ctypes.windll.kernel32.TerminateProcess(hProcess, 0)
        ctypes.windll.kernel32.CloseHandle(hProcess)
    else:
        os.kill(popen.pid, signal.SIGKILL)

    if popens[sid].__dict__.get("_kill", False):
        popens.pop(sid)

def create_if_not_exists() -> None:
    """Creates a file for recording services if it does not exist."""
    if PROC_FILE.exists():
        return
    
    with open(PROC_FILE, "x", encoding=ENCODING) as writer:
        writer.write("[]")

def add_service(
    type: str,
    name: str,
    command: list[str],
    cwd: Optional[str],
    description: Optional[str],
    autorun: bool
) -> None:
    """Adds the specified service to the list (registers it)."""
    create_if_not_exists()
    with open(PROC_FILE, "r", encoding=ENCODING) as reader:
        services = simdjson.loads(reader.read())

    services.append({"type": type, "name": name, "command": command, "cwd": cwd,
                     "description": description, "autorun": autorun})

    with open(PROC_FILE, "w", encoding=ENCODING) as file:
        file.write(simdjson.dumps(services, ensure_ascii=False))

def remove_service(name: str) -> None:
    """Removes the specified service from the list (unregisters it)."""
    create_if_not_exists()
    with open(PROC_FILE, "r", encoding=ENCODING) as reader:
        services = simdjson.loads(reader.read())

    with open(PROC_FILE, "w", encoding=ENCODING) as file:
        file.write(simdjson.dumps([s for s in services if s["name"] != name], ensure_ascii=False))

def get_service(name: str) -> Optional[dict[str, Any]]:
    """Receives service data for its launch."""
    create_if_not_exists()
    with open(PROC_FILE, "r", encoding=ENCODING) as reader:
        services = simdjson.loads(reader.read())
    
    service = [s for s in services if s["name"] == name]
    return service[0] if len(service) > 0 else None

def list_services() -> list[dict[str, Any]]:
    """Lists all registered services."""
    create_if_not_exists()
    with open(PROC_FILE, "r", encoding=ENCODING) as reader:
        services = simdjson.loads(reader.read())

    return services

def read_string(buffer: io.BytesIO) -> str:
    """Reads the string until the end."""
    output = b""
    while (char := buffer.read(1)) != b"\x00":
        output += char
    
    return output.decode(ENCODING)

def encode_service(service: dict[str, Any]) -> bytes:
    """Encodes the :param:`service` as bytes."""
    popen = popens.get(service["name"])
    pid = popen.pid if popen is not None else 0

    type = service["type"]
    name = service["name"].encode(ENCODING)
    command = "".join(service["command"]).encode(ENCODING)
    cwd = (service["cwd"] or "").encode(ENCODING)
    description = (service["description"] or "").encode(ENCODING)
    autorun = service["autorun"]

    return struct.pack(f">B{len(name)}sB{len(command)}sB{len(cwd)}sB{len(description)}sB?I",
                       type, name, 0, command, 0, cwd, 0, description, 0, autorun, pid)

def run_service(service: dict[str, Any]) -> Popen:
    """Starts the specified :param:`service`."""
    cwd = service["cwd"]
    args = shlex.split(service["command"])
    args[0] = args[0] if cwd is None else os.path.join(cwd, args[0])

    popen = Popen(args, stdout=DEVNULL, stderr=DEVNULL, cwd=cwd)
    popens[service["name"]] = popen
    return popen

def handle(packet_type: int, data: io.BytesIO) -> Optional[bytes]:
    """Handles and attempts to execute the received command."""
    if packet_type == 0x00:  # 0x00 INFO
        # Why 4 bytes for PID?
        # Well, let's start with the fact that this project was originally
        # designed for Windows, where PID cannot exceed 4 bytes.
        #
        # Yes, this project can be run on Linux in theory, I haven't tested
        # it in practice. Even so there, the default limit does not exceed
        # 4 bytes.
        return struct.pack(">8sI", "plannerB".encode(ENCODING), os.getpid())
    
    if packet_type == 0x01:  # 0x01 REGISTER
        type = struct.unpack(">B", data.read(1))[0]  # type MUST BE greater than 0
        name = read_string(data)
        command = shlex.split(read_string(data))
        cwd = None if (value := read_string(data)) == "" else os.path.abspath(value)
        description = read_string(data) or None
        autorun = struct.unpack(">?", data.read(1))[0]

        service = get_service(name)
        if service is not None:
            return struct.pack(">B", 0)

        add_service(type, name, command, cwd, description, autorun)
        return struct.pack(">B", 1)
    
    if packet_type == 0x02:  # 0x02 UNREGISTER
        name = read_string(data)
        service = get_service(name)
        if service is None:
            return struct.pack(">BI", 0, 0)

        remove_service(name)
        popen = popens.get(name)
        if popen is not None:
            pid = popen.pid
            Thread(target=stop_service, args=(name,), daemon=True).start()
            return struct.pack(">BI", 1, pid)
        
        return struct.pack(">BI", 2, 0)

    if packet_type == 0x10:  # 0x10 GET SERVICE
        name = read_string(data)
        service = get_service(name)
        if service is None:
            return struct.pack(">B", 0)
        
        return encode_service(service)
    
    if packet_type == 0x11:  # 0x11 LIST SERVICES
        services = list_services()
        response = struct.pack(">I", len(services))
        for service in services:
            response += encode_service(service)
        
        return response

    if packet_type == 0x12:  # 0x12 RUN SERVICE
        name = read_string(data)
        service = get_service(name)
        if service is None:
            return struct.pack(">BI", 0, 0)  # service isn't exists

        if name in popens:
            pid = popens[name].pid
            return struct.pack(">BI", 1, pid)  # service is already up

        popen = run_service(service)
        return struct.pack(">BI", 2, popen.pid)
    
    if packet_type == 0x13:  # 0x13 STOP SERVICE
        name = read_string(data)
        service = get_service(name)
        if service is None:
            return struct.pack(">BI", 0, 0)  # service isn't exists

        if name not in popens:
            return struct.pack(">BI", 1, 0)  # service hasn't yet been launched

        pid = popens[name].pid
        Thread(target=stop_service, args=(name,), daemon=True).start()
        return struct.pack(">BI", 2, pid)
    
    if packet_type == 0x14:  # 0x14 RESTART SERVICE
        name = read_string(data)
        service = get_service(name)
        if service is None:
            return struct.pack(">BII", 0, 0, 0)  # service isn't exists

        if name not in popens:
            return struct.pack(">BII", 1, 0, 0)  # service hasn't yet been launched
        
        pid1 = popens[name].pid
        Thread(target=stop_service, args=(name,), daemon=True).start()
        pid2 = run_service(service).pid
        return struct.pack(">BII", 2, pid1, pid2)

def state_audit() -> None:
    """Checks whether the processes under its control are alive every 5
    seconds (if you haven't changed anything)."""
    while True:
        for sid, popen in popens.copy().items():
            if popen.poll() is None:
                continue

            popens.pop(sid)

        time.sleep(STATE_AUDIT_COOLDOWN)

def autorun() -> None:
    """Starts all services that require it automatically."""
    for service in list_services():
        if not service.get("autorun", False):
            continue

        run_service(service)

def try_to_bind(server: socket.socket, *, port: int = PORT) -> None:
    """Attempts to bind the specified :param:`server` to the constant host
    and port."""
    if port > PORT_LIMIT:
        sys.exit(0)

    try:
        server.bind((HOST, port))
    except socket.error as error:
        if error.errno == errno.EADDRINUSE:   # if the address with that port is already taken by someone else,
            try_to_bind(server, port=port+1)  # then try to start on the next port.
        
        raise error

def serve() -> None:
    """Accepts commands from the CLI and executes them.
    
    WARNING! Does not claim to be safe. In this project, all safety is your
    responsibility, not mine."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try_to_bind(server)
    
    server.listen(1)
    while True:
        connection, _ = server.accept()
        try:
            data = io.BytesIO(connection.recv(1024))
        except:
            continue
        
        response = handle(struct.unpack(">B", data.read(1))[0], data)
        if response is not None:
            connection.send(response)

        connection.close()

def main() -> None:
    """The entrypoint of background part."""
    Thread(target=state_audit, daemon=True).start()
    Thread(target=autorun).start()
    Thread(target=serve).start()

if __name__ == "__main__":
    main()
