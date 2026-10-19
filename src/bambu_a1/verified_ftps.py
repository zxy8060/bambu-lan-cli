"""A1 implicit FTPS, chain+hostname checked; no credentials in arguments/logs."""

import ftplib
import socket
from .signed_lan import lan


class VerifiedFTPS(ftplib.FTP_TLS):
    def __init__(self, cfg):
        self.cfg = cfg
        super().__init__(context=lan.context(), timeout=15)

    def connect(self):
        self.host, self.port = self.cfg["host"], 990
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock = self.context.wrap_socket(raw, server_hostname=self.cfg["serial"])
        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def makepasv(self):
        _, port = super().makepasv()
        return self.cfg["host"], port

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(
                conn, server_hostname=self.cfg["serial"], session=self.sock.session
            )
        return conn, size

    def readback(self, name, expected_size):
        if "/" in name or "\\" in name or "\r" in name or "\n" in name:
            raise ValueError("Invalid remote basename")
        self.voidcmd("TYPE I")
        chunks = bytearray()
        with self.transfercmd("RETR " + name) as data:
            while True:
                block = data.recv(65536)
                if not block:
                    break
                chunks.extend(block)
                if len(chunks) > expected_size:
                    raise ValueError("Remote file exceeds reviewed size")
        self.voidresp()
        if len(chunks) != expected_size:
            raise ValueError("Remote file size mismatch")
        return bytes(chunks)

    def upload_new(self, name, content):
        if not name.startswith("a1cli_") or any(c in name for c in "/\\\r\n"):
            raise ValueError("Invalid remote basename")
        self.voidcmd("TYPE I")
        try:
            self.size(name)
        except ftplib.error_perm as error:
            if not str(error).startswith("550"):
                raise
        else:
            raise RuntimeError("Remote filename exists; refusing overwrite")
        with self.transfercmd("STOR " + name) as data:
            data.sendall(content)
        self.voidresp()
