class ReplayCursor:
    """
    Tracks the progression of incremental replay.
    Aligns the snapshot's sequence_id with the incoming event stream sequence_ids.
    """
    
    def __init__(self, snapshot_sequence: int = 0):
        self.snapshot_sequence = snapshot_sequence
        self.last_event_sequence = snapshot_sequence
        self.events_processed = 0

    def advance(self, event_sequence: int) -> bool:
        """
        Advances the cursor if the event sequence is strictly contiguous.
        Returns True if successful, False if there's a gap or order violation.
        """
        if event_sequence <= self.snapshot_sequence:
            # This event is already covered by the snapshot
            return True
            
        if event_sequence == self.last_event_sequence + 1:
            self.last_event_sequence = event_sequence
            self.events_processed += 1
            return True
            
        return False

    def get_progress(self) -> dict:
        return {
            "snapshot_sequence": self.snapshot_sequence,
            "last_event_sequence": self.last_event_sequence,
            "events_processed": self.events_processed
        }
