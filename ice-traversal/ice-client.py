#!/usr/bin/env python

import argparse
import asyncio
import json
import logging
import os
import time
import aioice
import websockets

from quic_protocol import EchoClientProtocol
import m_socket
from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio import connect

STUN_SERVER = ("stun.l.google.com", 19302)
WEBSOCKET_URI = "wss://ice-traversal-98d95d2795d5.herokuapp.com"

async def run_quic_client(sock, remote_host, remote_port):
    print("establishing QUIC connection")
    configuration = QuicConfiguration(is_client=True)
    configuration.load_verify_locations("../../certs/pycacert.pem")

    async with connect(remote_host, remote_port, configuration=configuration, create_protocol=EchoClientProtocol, sock=sock) as protocol:
        stream_id = protocol._quic.get_next_available_stream_id()
        protocol._quic.send_stream_data(stream_id, b"Hello!", end_stream=True)
        received_data = await protocol.received_data.get()
        print("Data Received:", received_data)

async def answer(options):
    print("now", time.time())
    connection = aioice.Connection(
        ice_controlling=False, components=options.components, stun_server=STUN_SERVER
    )
    await connection.gather_candidates()

    websocket = await websockets.connect(WEBSOCKET_URI)

    # await offer
    message = json.loads(await websocket.recv())
    print("received offer", message)
    for c in message["candidates"]:
        await connection.add_remote_candidate(aioice.Candidate.from_sdp(c))
    await connection.add_remote_candidate(None)
    connection.remote_username = message["username"]
    connection.remote_password = message["password"]

    # send answer
    await websocket.send(
        json.dumps(
            {
                "candidates": [c.to_sdp() for c in connection.local_candidates],
                "password": connection.local_password,
                "username": connection.local_username,
            }
        )
    )

    await websocket.close()

    await connection.connect()
    remote_addr = connection.established_remote_addr

    sock = connection.sock
    # sock = await m_socket.create_socket(local_addr[0], local_addr[1])
    await run_quic_client(sock, remote_addr[0], remote_addr[1])

    await asyncio.sleep(5)
    await connection.close()


parser = argparse.ArgumentParser(description="ICE tester")
# parser.add_argument("action", choices=["offer", "answer"])
parser.add_argument("--components", type=int, default=1)
options = parser.parse_args()

logging.basicConfig(level=logging.DEBUG)

asyncio.get_event_loop().run_until_complete(answer(options))
