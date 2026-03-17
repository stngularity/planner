"""Common components of the CLI and the background process."""

__all__ = ("ENCODING", "HOST", "PORT", "PORT_OFFSET_LIMIT", "Buffer")

ENCODING: str = "utf-8"

HOST: str = "127.0.0.1"
PORT: int = 14561  # I don't remember why I chose this particular port.
PORT_OFFSET_LIMIT: int = 10


class Buffer:
    """A class for easily reading binary data."""

    def __init__(self, data: bytes) -> None:
        # print(f"buffer: init({data.hex()}, {len(data)})")
        self._data = data
        self._pos = 0
    
    def skip(self, n: int) -> None:
        """Skips the specified number of bytes."""
        # print(f"buffer: skip({n})")
        self._pos += n
    
    def read(self, n: int = 1) -> bytes:
        """:class:`bytes`: Reads the specified number of bytes."""
        output = self._data[self._pos:min(self._pos+n, len(self._data))]
        # print(f"buffer: read({self._pos}:{self._pos+n}): {output.hex()}")
        self._pos += n
        return output
    
    def read_string(self) -> str:
        """:class:`str`: Attempts to read a string from the specified buffer."""
        eos = self._data.find(b"\x00", self._pos)
        if eos == -1:
            # print(f"buffer: read({self._pos}): no string")
            return ""
        
        output = self._data[self._pos:eos].decode(ENCODING)
        # print(f"buffer: read({self._pos}:{eos}): {output}")
        self._pos = eos+1
        return output
    
    def skip_string(self) -> None:
        """Skips one string."""
        eos = self._data.find(b"\x00", self._pos)
        if eos != -1:
            self._pos = eos+1
    
    def __getitem__(self, index: int):
        return self._data[index]
