"""
core/ipc/pipe_transport.py
Synchronous Windows Named Pipe transport for Phase 11 IPC.

- Uses thread-blocking win32file/win32pipe operations to avoid fragile asyncio overlapped I/O.
- Enforces strict ACLs so only the current user can connect.
"""

import threading
import logging
import time

try:
    import win32pipe
    import win32file
    import win32security
    import win32api
    import win32con
    import pywintypes
except ImportError:
    win32pipe = win32file = win32security = win32api = win32con = pywintypes = None

from core.contracts.runtime_events import TransportState
from core.ipc.binary_transport import BinaryTransport, TransportError

logger = logging.getLogger(__name__)

PIPE_NAME = r"\\.\pipe\novamind_ipc"

class PipeTransport(BinaryTransport):
    def __init__(self, role: str = "KERNEL", pipe_name: str = PIPE_NAME):
        super().__init__(role=role)
        self.pipe_name = pipe_name
        self._pipe_handle = None
        self._connected_event = threading.Event()
        self._listener_thread = None

    def _create_security_attributes(self):
        """
        Creates Security Attributes that only allow the current user to Read/Write.
        """
        if not win32security:
            raise TransportError("pywin32 is required for PipeTransport")
            
        sd = win32security.SECURITY_DESCRIPTOR()
        user, domain, type_ = win32security.LookupAccountName(None, win32api.GetUserName())
        
        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.GENERIC_READ | win32con.GENERIC_WRITE, user)
        sd.SetSecurityDescriptorDacl(1, dacl, 0)
        
        sa = win32security.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        sa.bInheritHandle = False
        return sa

    def _connect_impl(self) -> None:
        """
        Creates the named pipe handle synchronously, but defers blocking `ConnectNamedPipe`
        to a listener thread so we don't stall the system boot.
        """
        if not win32pipe:
            raise TransportError("pywin32 not available")
            
        sa = self._create_security_attributes()
        
        # Open pipe synchronously (No FILE_FLAG_OVERLAPPED)
        try:
            self._pipe_handle = win32pipe.CreateNamedPipe(
                self.pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                1, # Max instances
                16 * 1024 * 1024, # Out buffer size
                16 * 1024 * 1024, # In buffer size
                0, # default timeout
                sa
            )
        except pywintypes.error as e:
            raise TransportError(f"Failed to create named pipe: {e}")

        # Start a thread to wait for client connection
        self._listener_thread = threading.Thread(target=self._wait_for_client, daemon=True, name="PipeListener")
        self._listener_thread.start()

    def _wait_for_client(self):
        """
        Blocks until the Godot client connects.
        """
        logger.info(f"[PipeTransport] Waiting for client connection on {self.pipe_name}...")
        try:
            # This blocks! But since it's in a background thread, the main thread can proceed to READY.
            win32pipe.ConnectNamedPipe(self._pipe_handle, None)
            logger.info("[PipeTransport] Client connected!")
            self._connected_event.set()
        except pywintypes.error as e:
            if e.winerror == 536:  # ERROR_PIPE_CONNECTED (Client connected before we called ConnectNamedPipe)
                logger.info("[PipeTransport] Client was already connected!")
                self._connected_event.set()
            elif e.winerror == 995: # ERROR_OPERATION_ABORTED (We closed it)
                pass
            else:
                logger.error(f"[PipeTransport] ConnectNamedPipe failed: {e}")

    def _disconnect_impl(self) -> None:
        if self._pipe_handle:
            try:
                win32pipe.DisconnectNamedPipe(self._pipe_handle)
                win32file.CloseHandle(self._pipe_handle)
            except pywintypes.error as e:
                logger.warning(f"[PipeTransport] Error closing pipe: {e}")
            finally:
                self._pipe_handle = None

    def _read_bytes(self, n: int, timeout: float) -> bytes:
        """
        Synchronous read. We simulate the timeout by blocking on the file handle.
        Warning: win32file.ReadFile on a synchronous pipe will block indefinitely if there's no data.
        To handle timeouts properly, we can peek at the pipe.
        """
        if not self._connected_event.is_set():
            # Wait for connection up to the timeout
            if not self._connected_event.wait(timeout):
                return b""
                
        start = time.time()
        buf = b""
        while len(buf) < n:
            time_left = timeout - (time.time() - start)
            if time_left <= 0:
                break
                
            try:
                # Peek to see if data is available before blocking
                avail, total_msg, left_msg = win32pipe.PeekNamedPipe(self._pipe_handle, 0)
                if avail > 0:
                    read_len = min(n - len(buf), avail)
                    hr, data = win32file.ReadFile(self._pipe_handle, read_len)
                    buf += data
                else:
                    # Sleep briefly to yield instead of busy waiting tightly
                    time.sleep(0.01)
            except pywintypes.error as e:
                # 109 = ERROR_BROKEN_PIPE
                if e.winerror == 109:
                    break
                raise TransportError(f"Read error: {e}")
                
        return buf

    def _write_bytes(self, data: bytes) -> None:
        if not self._connected_event.is_set():
            raise TransportError("Cannot write before client connects")
            
        try:
            hr, written = win32file.WriteFile(self._pipe_handle, data)
            if written != len(data):
                raise TransportError(f"Incomplete write: {written}/{len(data)} bytes")
        except pywintypes.error as e:
            if e.winerror == 109:
                raise TransportError("Broken pipe during write")
            raise TransportError(f"Write error: {e}")

    def _flush(self) -> None:
        if self._pipe_handle:
            try:
                win32file.FlushFileBuffers(self._pipe_handle)
            except pywintypes.error:
                pass
