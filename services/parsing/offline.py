"""Deny Python network egress in fixed library runners, including download helpers.

This complements local-only model configuration; it is not an OS sandbox for
native extensions. Do not run user code in this interpreter.
"""
import os
import socket

OFFLINE_ENV = {
    'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK': 'True',
    'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1',
    'HF_HUB_DISABLE_TELEMETRY': '1', 'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1',
    'DO_NOT_TRACK': '1', 'YOLO_OFFLINE': 'true',
}


def disable_network():
    # Also applies to the short-lived VL helper interpreters. Socket patches
    # are process-local, whereas library offline flags must survive exec().
    os.environ.update(OFFLINE_ENV)
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
