from __future__ import annotations

import asyncio
import json


class TorControlError(RuntimeError):
    pass


async def request_newnym(host: str, port: int, password: str | None) -> None:
    """Ask a local Tor ControlPort for a new circuit.

    The password must be the plaintext value used to create Tor's
    HashedControlPassword; the hash itself cannot authenticate a client.
    """
    if not password:
        raise TorControlError("TOR_CONTROL_PASSWORD is required")
    try:
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(f"AUTHENTICATE {json.dumps(password)}\r\n".encode())
        await writer.drain()
        auth = await reader.readline()
        if not auth.startswith(b"250"):
            raise TorControlError(auth.decode(errors="replace").strip())
        writer.write(b"SIGNAL NEWNYM\r\nQUIT\r\n")
        await writer.drain()
        response = await reader.readline()
        writer.close()
        await writer.wait_closed()
        if not response.startswith(b"250"):
            raise TorControlError(response.decode(errors="replace").strip())
    except OSError as exc:
        raise TorControlError(str(exc)) from exc
