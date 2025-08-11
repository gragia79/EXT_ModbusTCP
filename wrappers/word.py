# wrappers/word.py
# WORD (16-bit) wrapper with change-tracking and numeric setter/getter.

class Word:
    """Represents a 16-bit WORD with change tracking."""
    def __init__(self, name, address, description=""):
        self.name = name                    # variable name
        self.address = address              # address like "%MW10"
        self.description = description      # description string
        self._value = None                  # stored numeric value
        self._last_value = None             # previous numeric value
        self._changed = False               # change flag

    @property
    def value(self):
        """Return current numeric value."""
        return self._value

    @value.setter
    def value(self, val):
        """Set numeric value, update changed flag if different."""
        # attempt to coerce to int unless None
        if val is not None:
            try:
                val = int(val)
            except Exception:
                # if conversion fails, keep the raw value
                pass
        if self._value != val:              # compare with previous
            self._changed = True            # mark changed if different
            self._last_value = self._value  # save last value
        self._value = val                   # set current value

    def set(self, val):
        """Alias for setting value (explicit method)."""
        self.value = val

    def update(self, new_value):
        """Update from Modbus read or external source."""
        self.value = new_value

    def isChanged(self):
        """Return and reset the changed flag (resets on read)."""
        changed = self._changed
        self._changed = False
        return changed

    def resetChanged(self):
        """Explicitly reset changed flag (alternative to isChanged())."""
        self._changed = False

    def __repr__(self):
        """Developer-friendly representation."""
        return f"<Word {self.name}={self._value}>"
