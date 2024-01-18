import socket

async def create_socket(local_host, local_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    completed = False
    try:
        sock.bind((local_host, local_port))
        completed = True
    finally:
        if not completed:
            sock.close()
    return sock
