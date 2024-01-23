import asyncio
import m_socket
from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

class EchoClientProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received_data = asyncio.Queue()

    def quic_event_received(self, event):
        print("Received: ", event)
        if isinstance(event, StreamDataReceived):
            self.received_data.put_nowait(event.data)
            if event.end_stream:
                self.close()

async def run_quic_client():
    configuration = QuicConfiguration(is_client=True)
    configuration.load_verify_locations("../../certs/pycacert.pem")
    sock = await m_socket.create_socket("127.0.0.1", 12345)
    # 104.154.130.33
    async with connect("localhost", 12346, configuration=configuration, create_protocol=EchoClientProtocol, local_port=12345, sock=sock) as protocol:
        stream_id = protocol._quic.get_next_available_stream_id()
        protocol._quic.send_stream_data(stream_id, b"Hello!", end_stream=False)
        received_data = await protocol.received_data.get()
        print("Data Received:", received_data)

if __name__ == "__main__":
    asyncio.run(run_quic_client())
