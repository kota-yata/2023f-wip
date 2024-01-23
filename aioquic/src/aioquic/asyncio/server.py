import asyncio
import os
from functools import partial
from typing import Callable, Dict, Optional, Text, Union, cast

from ..buffer import Buffer
from ..quic.configuration import SMALLEST_MAX_DATAGRAM_SIZE, QuicConfiguration
from ..quic.connection import NetworkAddress, QuicConnection
from ..quic.packet import (
    PACKET_TYPE_INITIAL,
    encode_quic_retry,
    encode_quic_version_negotiation,
    pull_quic_header,
)
from ..quic.retry import QuicRetryTokenHandler
from ..tls import SessionTicketFetcher, SessionTicketHandler
from .protocol import QuicConnectionProtocol, QuicStreamHandler

import socket

__all__ = ["serve"]


class QuicServer(asyncio.DatagramProtocol):
    def __init__(
        self,
        *,
        configuration: QuicConfiguration,
        create_protocol: Callable = QuicConnectionProtocol,
        session_ticket_fetcher: Optional[SessionTicketFetcher] = None,
        session_ticket_handler: Optional[SessionTicketHandler] = None,
        retry: bool = False,
        stream_handler: Optional[QuicStreamHandler] = None,
    ) -> None:
        self._configuration = configuration
        self._create_protocol = create_protocol
        self._loop = asyncio.get_event_loop()
        self._protocols: Dict[bytes, QuicConnectionProtocol] = {}
        self._session_ticket_fetcher = session_ticket_fetcher
        self._session_ticket_handler = session_ticket_handler
        self._transport: Optional[asyncio.DatagramTransport] = None

        self._stream_handler = stream_handler

        if retry:
            self._retry = QuicRetryTokenHandler()
        else:
            self._retry = None

    async def connect(self, addr):
        print("connecting")
        connection = QuicConnection(
            configuration=self._configuration,
            session_ticket_handler=self._session_ticket_handler,
            token_handler=None,
        )
        protocol = self._create_protocol(connection, stream_handler=self._stream_handler)
        try:
            protocol.connect(addr)
            await asyncio.sleep(3)
        finally:
            print("closing")
            # protocol.close()
            # await protocol.wait_closed()

    def close(self):
        for protocol in set(self._protocols.values()):
            protocol.close()
        self._protocols.clear()
        self._transport.close()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = cast(asyncio.DatagramTransport, transport)

    def datagram_received(self, data: Union[bytes, Text], addr: NetworkAddress) -> None:
        print("datagram_received from: ", addr)
        data = cast(bytes, data)
        buf = Buffer(data=data)

        try:
            header = pull_quic_header(
                buf, host_cid_length=self._configuration.connection_id_length
            )
        except ValueError:
            print("Not a QUIC packet")
            return

        # version negotiation
        if (
            header.version is not None
            and header.version not in self._configuration.supported_versions
        ):
            self._transport.sendto(
                encode_quic_version_negotiation(
                    source_cid=header.destination_cid,
                    destination_cid=header.source_cid,
                    supported_versions=self._configuration.supported_versions,
                ),
                addr,
            )
            return

        protocol = self._protocols.get(header.destination_cid, None)
        original_destination_connection_id: Optional[bytes] = None
        retry_source_connection_id: Optional[bytes] = None
        if (
            protocol is None
            and len(data) >= SMALLEST_MAX_DATAGRAM_SIZE
            and header.packet_type == PACKET_TYPE_INITIAL
        ):
            self._configuration.is_client = False
            # retry
            if self._retry is not None:
                if not header.token:
                    # create a retry token
                    source_cid = os.urandom(8)
                    self._transport.sendto(
                        encode_quic_retry(
                            version=header.version,
                            source_cid=source_cid,
                            destination_cid=header.source_cid,
                            original_destination_cid=header.destination_cid,
                            retry_token=self._retry.create_token(
                                addr, header.destination_cid, source_cid
                            ),
                        ),
                        addr,
                    )
                    return
                else:
                    # validate retry token
                    try:
                        (
                            original_destination_connection_id,
                            retry_source_connection_id,
                        ) = self._retry.validate_token(addr, header.token)
                    except ValueError:
                        return
            else:
                original_destination_connection_id = header.destination_cid

            # create new connection
            connection = QuicConnection(
                configuration=self._configuration,
                original_destination_connection_id=original_destination_connection_id,
                retry_source_connection_id=retry_source_connection_id,
                session_ticket_fetcher=self._session_ticket_fetcher,
                session_ticket_handler=self._session_ticket_handler,
            )
            protocol = self._create_protocol(
                connection, stream_handler=self._stream_handler
            )
            protocol.connection_made(self._transport)

            # register callbacks
            protocol._connection_id_issued_handler = partial(
                self._connection_id_issued, protocol=protocol
            )
            protocol._connection_id_retired_handler = partial(
                self._connection_id_retired, protocol=protocol
            )
            protocol._connection_terminated_handler = partial(
                self._connection_terminated, protocol=protocol
            )

            self._protocols[header.destination_cid] = protocol
            self._protocols[connection.host_cid] = protocol

        if protocol is not None:
            protocol.datagram_received(data, addr)

    def _connection_id_issued(self, cid: bytes, protocol: QuicConnectionProtocol):
        self._protocols[cid] = protocol

    def _connection_id_retired(
        self, cid: bytes, protocol: QuicConnectionProtocol
    ) -> None:
        assert self._protocols[cid] == protocol
        del self._protocols[cid]

    def _connection_terminated(self, protocol: QuicConnectionProtocol):
        for cid, proto in list(self._protocols.items()):
            if proto == protocol:
                del self._protocols[cid]

async def serve(
    *,
    configuration: QuicConfiguration,
    create_protocol: Callable = QuicConnectionProtocol,
    session_ticket_fetcher: Optional[SessionTicketFetcher] = None,
    session_ticket_handler: Optional[SessionTicketHandler] = None,
    retry: bool = False,
    stream_handler: QuicStreamHandler = None,
    sock = None,
    connect = False,
    remote_host = None,
    remote_port = None,
) -> QuicServer:
    """
    Start a QUIC server at the given `host` and `port`.

    :func:`serve` requires a :class:`~aioquic.quic.configuration.QuicConfiguration`
    containing TLS certificate and private key as the ``configuration`` argument.

    :func:`serve` also accepts the following optional arguments:

    * ``create_protocol`` allows customizing the :class:`~asyncio.Protocol` that
      manages the connection. It should be a callable or class accepting the same
      arguments as :class:`~aioquic.asyncio.QuicConnectionProtocol` and returning
      an instance of :class:`~aioquic.asyncio.QuicConnectionProtocol` or a subclass.
    * ``session_ticket_fetcher`` is a callback which is invoked by the TLS
      engine when a session ticket is presented by the peer. It should return
      the session ticket with the specified ID or `None` if it is not found.
    * ``session_ticket_handler`` is a callback which is invoked by the TLS
      engine when a new session ticket is issued. It should store the session
      ticket for future lookup.
    * ``retry`` specifies whether client addresses should be validated prior to
      the cryptographic handshake using a retry packet.
    * ``stream_handler`` is a callback which is invoked whenever a stream is
      created. It must accept two arguments: a :class:`asyncio.StreamReader`
      and a :class:`asyncio.StreamWriter`.
    """

    loop = asyncio.get_event_loop()

    configuration.server_name = remote_host
    configuration.is_client = True

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: QuicServer(
            configuration=configuration,
            create_protocol=create_protocol,
            session_ticket_fetcher=session_ticket_fetcher,
            session_ticket_handler=session_ticket_handler,
            retry=retry,
            stream_handler=stream_handler,
        ),
        sock=sock,
        # local_addr=(host, port),
    )
    print("serving on", protocol._transport.get_extra_info("sockname"))
    if not connect:
      return protocol
    
    # 最初にconnectする処理を追加
    connection = QuicConnection(
        configuration=configuration,
        session_ticket_handler=session_ticket_handler,
        token_handler=None,
    )
    protocol = cast(QuicConnectionProtocol, protocol)
    infos = await loop.getaddrinfo(remote_host, remote_port, type=socket.SOCK_DGRAM, family=socket.AF_INET)
    addr = infos[0][4]
    await protocol.connect(addr)
    
    return protocol
