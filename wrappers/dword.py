# wrappers/dword.py
# DWORD (32-bit) wrapper — same pattern as Word but for 32-bit values.

class DWord:
    """Represents a 32-bit DWORD with change tracking."""
    def __init__(self, name, address, description=""):
        self.name = name
        self.address = address
        self.description = description
        self._value = None
        self._last_value = None
        self._changed = False

    @property
    def value(self):
        """Return the 32-bit integer value."""
        return self._value

    @value.setter
    def value(self, val):
        """Set 32-bit value, try to convert to int if possible."""
        if val is not None:
            try:
                val = int(val)
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
        """Return and reset change flag."""
        changed = self._changed
        self._changed = False
        return changed

    def __repr__(self):
        """Developer-friendly representation."""
        return f"<DWord {self.name}={self._value}>"
