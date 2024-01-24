import asyncio
import os
from aioquic.asyncio import serve, connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

class EchoQuicProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def quic_event_received(self, event):
        print("Received: ", event)
        if isinstance(event, StreamDataReceived):
            self._quic.send_stream_data(event.stream_id, b"Hole Punching", end_stream=True)
            if event.end_stream:
                self.close()

async def run_quic_server():
    configuration = QuicConfiguration(is_client=False)
    configuration.load_verify_locations("./certs/pycacert.pem")
    configuration.load_cert_chain("./certs/cert.pem", "./certs/key.pem")
    await serve("0.0.0.0", int(os.environ.get("PORT", 5000)), configuration=configuration, create_protocol=EchoQuicProtocol)
    await asyncio.Future()

async def main():
    # sock = await m_socket.create_socket("localhost", 12346)
    server_task = asyncio.create_task(run_quic_server())
    await asyncio.gather(server_task)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Server terminated with an exception: {e}")
