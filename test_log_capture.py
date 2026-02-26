import sys
import collections
import io

class DualStream:
    def __init__(self, original_stream, maxlen=100):
        self.original_stream = original_stream
        self.buffer = collections.deque(maxlen=maxlen)
        self._current_chunk = ""

    def write(self, data):
        self.original_stream.write(data)
        self._current_chunk += data
        if '\n' in self._current_chunk:
            lines = self._current_chunk.split('\n')
            # All elements except the last one are complete lines
            for line in lines[:-1]:
                self.buffer.append(line)
            # The last element is the beginning of the next line
            self._current_chunk = lines[-1]

    def flush(self):
        self.original_stream.flush()

    def __getattr__(self, name):
        """Delegate missing methods (like fileno) to the original stream."""
        return getattr(self.original_stream, name)

    def get_logs(self, n=20):
        logs = list(self.buffer)
        if self._current_chunk:
            logs.append(self._current_chunk)
        return logs[-n:]


def test_log_capture():
    print("Starting Log Capture Test (Line-Based)...")
    
    # Save original stdout
    original_stdout = sys.stdout
    
    # Setup DualStream
    class MockStream(io.StringIO):
        def fileno(self): return 123
            
    mock_stdout = MockStream()
    wrapper = DualStream(mock_stdout)
    sys.stdout = wrapper
    
    # Generate some output with mixed newlines
    sys.stdout.write("Line 1\nLine 2")
    sys.stdout.write(" Cont.\nLine 3\n")
    
    # Restore stdout
    sys.stdout = original_stdout
    
    # Verify capture
    logs = wrapper.get_logs()
    print(f"Captured Logs: {logs}")
    
    # Verify line splitting
    assert "Line 1" in logs
    assert "Line 2 Cont." in logs
    assert "Line 3" in logs
    assert len(logs) >= 3
    
    print("Verification Successful: DualStream captured lines correctly without jumbling.")

if __name__ == "__main__":
    test_log_capture()
