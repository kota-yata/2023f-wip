import asyncio
import m_socket
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

async def run_quic_server(sock):
    configuration = QuicConfiguration(is_client=False)
    configuration.load_verify_locations("../../certs/pycacert.pem")
    configuration.load_cert_chain("../../certs/cert.pem", "../../certs/key.pem")
    await serve(configuration=configuration, create_protocol=EchoQuicProtocol, sock=sock, connect=True, remote_host="106.72.33.225", remote_port=12345)
    await asyncio.Future()

# async def run_quic_client(sock):
#     print("Running client")
#     configuration = QuicConfiguration(is_client=True)
#     configuration.load_verify_locations("../../tests/pycacert.pem")
#     async with connect("localhost", 12345, configuration=configuration, create_protocol=EchoQuicProtocol, local_port=12346, sock=sock) as protocol:
#         stream_id = protocol._quic.get_next_available_stream_id()
#         protocol._quic.send_stream_data(stream_id, b"Hello!", end_stream=False)
#         received_data = await protocol.received_data.get()
#         print("Data Received:", received_data)

async def main():
    sock = await m_socket.create_socket("10.128.0.2", 12346)
    server_task = asyncio.create_task(run_quic_server(sock))
    # client_task = asyncio.create_task(run_quic_client(sock))
    await asyncio.gather(server_task)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Server terminated with an exception: {e}")
