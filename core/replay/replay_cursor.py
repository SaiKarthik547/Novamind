class ReplayCursor:
    """
    Tracks the progression of incremental replay.
    Phase 11 introduces precise segmented cursor offsets for SALVAGE mode 
    and checkpoint restoration.
    """
    
    def __init__(self, 
                 snapshot_sequence: int = 0, 
                 segment_id: str = "00000",
                 byte_offset: int = 0,
                 event_index: int = 0,
                 event_hash: str = None):
        self.snapshot_sequence = snapshot_sequence
        self.last_event_sequence = snapshot_sequence
        self.events_processed = 0
        
        # Phase 11 Forensic Lineage attributes
        self.segment_id = segment_id
        self.byte_offset = byte_offset
        self.event_index = event_index
        self.event_hash = event_hash

    def advance(self, event_sequence: int, segment_id: str, byte_offset: int, event_index: int, event_hash: str) -> bool:
        """
        Advances the cursor incrementally.
        """
        self.last_event_sequence = event_sequence
        self.events_processed += 1
        self.segment_id = segment_id
        self.byte_offset = byte_offset
        self.event_index = event_index
        self.event_hash = event_hash
        return True

    def get_progress(self) -> dict:
        return {
            "snapshot_sequence": self.snapshot_sequence,
            "last_event_sequence": self.last_event_sequence,
            "events_processed": self.events_processed,
            "segment_id": self.segment_id,
            "byte_offset": self.byte_offset,
            "event_index": self.event_index,
            "event_hash": self.event_hash
        }
