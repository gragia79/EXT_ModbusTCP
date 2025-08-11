# wrappers/byte.py
# BYTE (8-bit) wrapper — same pattern as Word but kept separate for clarity.

class Byte:
    """Represents an 8-bit BYTE with change tracking."""
    def __init__(self, name, address, description=""):
        self.name = name
        self.address = address
        self.description = description
        self._value = None
        self._last_value = None
        self._changed = False

    @property
    def value(self):
        """Return current byte value."""
        return self._value

    @value.setter
    def value(self, val):
        """Set byte value, attempt integer conversion when possible."""
        if val is not None:
            try:
                val = int(val) & 0xFF   # force to 0..255
            except Exception:
                pass
        if self._value != val:
            self._changed = True
            self._last_value = self._value
        self._value = val

    def update(self, new_value):
        """Update from Modbus read or external source."""
        self.value = new_value

    def isChanged(self):
        """Return and reset changed flag."""
        changed = self._changed
        self._changed = False
        return changed

    def __repr__(self):
        """Developer-friendly representation."""
        return f"<Byte {self.name}={self._value}>"
