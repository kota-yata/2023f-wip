import asyncio
import json
import sys
from aiortc import RTCPeerConnection, RTCDataChannel, RTCSessionDescription
from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

async def run(peer_connection: RTCPeerConnection, is_offer: bool):
    if is_offer:
        data_channel = peer_connection.createDataChannel("chat")
        offer = await peer_connection.createOffer()
        await peer_connection.setLocalDescription(offer)
        print(json.dumps({"sdp": peer_connection.localDescription.sdp, "type": peer_connection.localDescription.type}))
        answer = json.loads(input("Enter answer: "))
        await peer_connection.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
    else:
        offer = json.loads(input("Enter offer: "))
        await peer_connection.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type=offer["type"]))

        answer = await peer_connection.createAnswer()
        await peer_connection.setLocalDescription(answer)
        print(json.dumps({"sdp": peer_connection.localDescription.sdp, "type": peer_connection.localDescription.type}))

    @peer_connection.on("icecandidate")
    async def on_icecandidate(candidate):
        print(json.dumps({"candidate": candidate}))
    
    @peer_connection.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state is {peer_connection.connectionState}")
        if peer_connection.connectionState in ["connected", "completed"]:
            print("Connection established!")


    await asyncio.sleep(30)

async def main():
    is_offer = len(sys.argv) > 1 and sys.argv[1] == "offer"
    peer_connection = RTCPeerConnection()
    try:
        await run(peer_connection, is_offer)
    finally:
        await peer_connection.close()

if __name__ == "__main__":
    asyncio.run(main())

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
    configuration.load_verify_locations("../tests/pycacert.pem")

    async with connect("localhost", 4433, configuration=configuration, create_protocol=EchoClientProtocol, local_port=12345) as protocol:
        stream_id = protocol._quic.get_next_available_stream_id()
        protocol._quic.send_stream_data(stream_id, b"Hello!", end_stream=False)
        received_data = await protocol.received_data.get()
        print("Data Received:", received_data)
