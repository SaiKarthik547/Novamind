import time
import threading
import unittest

from core.telemetry.telemetry_event import TelemetryEvent, TelemetryClass, ReplayIntegrityLevel
from core.telemetry.telemetry_bus import TelemetryBus, TelemetryOverflowPolicy
from core.telemetry.runtime_metrics import RuntimeMetrics, WorkerMetricsSnapshot

class TestTelemetryOrdering(unittest.TestCase):
    def test_metrics_ring_buffer(self):
        metrics = RuntimeMetrics(history_size=5)
        for i in range(10):
            metrics.record_worker_snapshot(
                WorkerMetricsSnapshot(
                    timestamp_ns=i,
                    worker_id="test_worker_1",
                    cpu_percent=10.0,
                    memory_mb=50.0,
                    queue_depth=1
                )
            )
        
        history = metrics.get_worker_history("test_worker_1")
        self.assertEqual(len(history), 5)
        # Should only contain the last 5 elements (timestamps 5-9)
        self.assertEqual([s.timestamp_ns for s in history], [5, 6, 7, 8, 9])

    def test_telemetry_bus_overflow_policies(self):
        bus = TelemetryBus(max_size=2)
        
        wal_received = []
        sink_received = []
        
        bus.register_wal(wal_received.append)
        bus.register_sink(sink_received.append)
        
        # Don't start the dispatch thread so we can easily fill the queue
        
        # Fill the queue
        bus.emit(TelemetryEvent("TEST", TelemetryClass.EPHEMERAL, {}))
        bus.emit(TelemetryEvent("TEST", TelemetryClass.EPHEMERAL, {}))
        
        # Queue is now full (size 2).
        
        # Test DROP_EPHEMERAL
        bus.emit(TelemetryEvent("DROPPED", TelemetryClass.EPHEMERAL, {}))
        self.assertEqual(bus._queue.qsize(), 2) # Still 2
        
        # Test FORENSIC drop (will block briefly and drop)
        bus.emit(TelemetryEvent("FORENSIC", TelemetryClass.FORENSIC, {}))
        self.assertEqual(bus._queue.qsize(), 2)

        # REPLAY_CRITICAL will block for timeout and raise RuntimeError (ESCALATE_PANIC)
        # We temporarily mock the timeout parameter in emit for fast testing
        start = time.time()
        with self.assertRaises(RuntimeError):
            # Patch put to timeout quickly just for the test
            original_put = bus._queue.put
            def fast_put(*args, **kwargs):
                kwargs['timeout'] = 0.1
                original_put(*args, **kwargs)
            bus._queue.put = fast_put
            
            try:
                bus.emit(TelemetryEvent("CRITICAL", TelemetryClass.REPLAY_CRITICAL, {}))
            finally:
                bus._queue.put = original_put
            
        # We will test the happy path dispatching
        bus.start()
        time.sleep(0.1) # Give time to flush
        self.assertEqual(bus._queue.qsize(), 0)
        
        # Emit a critical event, it should go to WAL
        bus.emit(TelemetryEvent("CRITICAL", TelemetryClass.REPLAY_CRITICAL, {}))
        
        # Emit forensic
        bus.emit(TelemetryEvent("FORENSIC", TelemetryClass.FORENSIC, {}))
        
        time.sleep(0.1)
        self.assertEqual(len(wal_received), 1)
        self.assertEqual(wal_received[0].telemetry_class, TelemetryClass.REPLAY_CRITICAL)
        
        self.assertEqual(len(sink_received), 1)
        self.assertEqual(sink_received[0].telemetry_class, TelemetryClass.FORENSIC)
        
        bus.stop()

if __name__ == '__main__':
    unittest.main()
