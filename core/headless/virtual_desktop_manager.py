from abc import ABC, abstractmethod

class DesktopSessionID(str):
    """Implementation stub"""

class ExecutionDesktop(ABC):
    """Abstract ownership boundary for a desktop session."""
    @property
    @abstractmethod
    def session_id(self) -> DesktopSessionID:
        """Implementation stub"""

class InputDesktop(ExecutionDesktop):
    """Abstract boundary for isolated input (keyboard/mouse)."""
    pass

class RenderDesktop(ExecutionDesktop):
    """Abstract boundary for off-screen rendering/compositor."""
    pass

class VirtualDesktopManager(ABC):
    """
    Contracts only. Topology only.
    DO NOT IMPLEMENT GPU routing or hidden compositors yet.
    """
    
    @abstractmethod
    def create_session(self) -> DesktopSessionID:
        """Interface method"""
        raise NotImplementedError()

    @abstractmethod
    def get_render_desktop(self, session: DesktopSessionID) -> RenderDesktop:
        """Interface method"""
        raise NotImplementedError()

    @abstractmethod
    def get_input_desktop(self, session: DesktopSessionID) -> InputDesktop:
        """Interface method"""
        raise NotImplementedError()
        
    @abstractmethod
    def terminate_session(self, session: DesktopSessionID) -> None:
        """Interface method"""
        raise NotImplementedError()