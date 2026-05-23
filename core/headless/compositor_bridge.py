from abc import ABC, abstractmethod

class CompositorBridge(ABC):
    """
    Abstract stream/mirroring hooks for future non-invasive screen grabbing.
    DO NOT IMPLEMENT full DWM hooking or mirroring yet.
    """
    @abstractmethod
    def request_frame(self, session_id: str) -> bytes:
        """Returns the latest compositor frame for a given session."""
        raise NotImplementedError()
        
    @abstractmethod
    def start_stream(self, session_id: str) -> bool:
        """Interface method"""
        raise NotImplementedError()
        
    @abstractmethod
    def stop_stream(self, session_id: str) -> None:
        """Interface method"""
        raise NotImplementedError()