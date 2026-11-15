"""Deny Python network egress in fixed library runners, including download helpers.

This complements local-only model configuration; it is not an OS sandbox for
native extensions. Do not run user code in this interpreter.
"""
import socket


def disable_network():
    def deny(*args, **kwargs):
        raise OSError('Parser network access disabled; provision models through the remote relay')

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto

    def connect(sock, address):
        if sock.family != socket.AF_UNIX:
            return deny()
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if sock.family != socket.AF_UNIX:
            return deny()
        return original_connect_ex(sock, address)

    def sendto(sock, *args):
        if sock.family != socket.AF_UNIX:
            return deny()
        return original_sendto(sock, *args)

    socket.getaddrinfo = deny
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
