# wrappers/flag.py
# Simple BOOL wrapper (Flag) with change-tracking and helper methods.

class Flag:
    """Represents a boolean flag (BOOL) with change tracking."""
    def __init__(self, name, address, description=""):
        self.name = name                    # variable name (string)
        self.address = address              # address string like "%IX0.0"
        self.description = description      # human-readable description
        self._value = None                  # actual stored value (private)
        self._last_value = None             # previous value (for comparison)
        self._changed = False               # flag changed state (True/False)

    @property
    def value(self):
        """Getter for the value property (returns current value)."""
        return self._value

    @value.setter
    def value(self, val):
        """Setter for the value property — updates and sets changed flag."""
        val = bool(val) if val is not None else None   # coerce to bool or None
        if self._value != val:                          # check if changed
            self._changed = True                       # mark as changed
            self._last_value = self._value             # store last value
        self._value = val                               # set new value

    def on(self):
        """Convenience: set flag to True."""
        self.value = True

    def off(self):
        """Convenience: set flag to False."""
        self.value = False

    def update(self, new_value):
        """Update value from outside (e.g., Modbus read)."""
        self.value = new_value

    def isChanged(self):
        """
        Return True if changed since last check, and reset the changed flag.
        This matches the requirement: isChanged() is re-set each time it's read.
        """
        changed = self._changed
        self._changed = False    # reset on access
        return changed

    def isSet(self):
        """Return True if flag is logically set (True)."""
        return bool(self._value) is True

    def isClear(self):
        """Return True if flag is logically clear (False or None)."""
        return not bool(self._value)

    def __repr__(self):
        """Developer-friendly representation."""
        return f"<Flag {self.name}={self._value}>"
