"""
ext_modbus_blueprint.py

Integrated Modbus wrapper:
- Parses Graziano's PLC-style variable file (Name AT %ADDR: TYPE [:=
  value]; // comment)
- Instantiates wrapper objects (Flag, Word, Byte, DWord) imported from
  wrappers/ package you already created.
- Builds address registry (canonical keys like MW100, MB6, MX8.0).
- Handles aliases (two names pointing to same address) by linking to same object.
- Implements synchronization:
    MW <-> MB <-> MX (bits)
- Implements alive() with retry policy (3 tries -> mark not alive and close)
- Simple PollingGroup helper to run a background poll loop (default 500 ms).
- Honors initial values (:=) by not overwriting them in demo unless forced.
"""

import os
import time
import logging
import threading
from typing import Tuple, Optional

from pyModbusTCP.client import ModbusClient

# Import your wrappers (you said you already created them)
from wrappers import Flag, Word, Byte, DWord

# Basic logger
logging.basicConfig(level=logging.INFO)


# ---------------------------
# Helper: parse address
# ---------------------------
def parse_address(addr: str) -> Tuple[str, int, Optional[int]]:
    """
    Normalize addresses like:
      %MW100  -> ('MW', 100, None)
      %MB6    -> ('MB', 6, None)
      %MX8.0  -> ('MX', 8, 0)
      %MD0    -> ('MD', 0, None)
      %IX0.0  -> ('IX', 0, 0)   (optional: treat as bit)
    """
    s = addr.strip()
    if s.startswith("%"):
        s = s[1:]
    # bit-address form: MX8.0 or IX0.0
    if "." in s:
        base = s[:2].upper()          # e.g. 'MX', 'IX'
        left, bit_s = s.split(".", 1)
        # Extract number after base letters
        num = int(left[2:]) if left[2:].isdigit() else int(left[1:])
        bit = int(bit_s)
        return base, num, bit
    else:
        base = s[:2].upper()
        num = int(s[2:])
        return base, num, None


def canonical_key(base: str, num: int, bit: Optional[int]) -> str:
    """Return canonical registry key."""
    if bit is None:
        return f"{base}{num}"
    else:
        return f"{base}{num}.{bit}"


# ---------------------------
# Timer wrapper (simple stub)
# ---------------------------
class TimerWrapper:
    """
    Simple timer structure as requested by the client:
    stores an address for timer value, value, and a flag.
    (We create a basic structure; later we can map it to PWM/time registers).
    """
    def __init__(self, name, address, description=""):
        self.name = name
        self.address = address
        self.description = description
        self.value = None       # numeric time (ms) or other
        self.flag = False       # boolean flag
        self._changed = False
        self.initial_value = None

    def update_value(self, v):
        if self.value != v:
            self._changed = True
        self.value = v

    def isChanged(self):
        changed = self._changed
        self._changed = False
        return changed


# ---------------------------
# Main Modbus wrapper class
# ---------------------------

class ModbusWrapper:
    def __init__(self, ip, port=502, unit_id=0, variable_file=None):
        # ASSUMPTION: Use pyModbusTCP client; auto_open False (we manage open)
        self.host = ip
        self.port = port
        self.unit_id = unit_id
        self.client = ModbusClient(
            host=self.host,
            port=self.port,
            unit_id=self.unit_id,
            auto_open=False,
            auto_close=False
        )
        self.last_alive = None
        self._alive_state = False
        self._alive_lock = threading.Lock()
        self.variables = {}      # name -> wrapper object (Flag/Word/Byte/DWord/TimerWrapper)
        self.registry = {}       # canonical address key -> wrapper object
        self.duplicates = {}     # canonical -> [names]
        self._sync_lock = threading.RLock()  # guard to avoid recursive sync

        # polling groups: name -> dict { thread, interval_ms, vars, stop_event }
        self.polling_groups = {}

        if variable_file:
            parsed = self.parse_variables_file(variable_file)
            self.instantiate_wrappers(parsed)
            # build registry from instantiated wrappers
            self.build_address_registry()
            # log duplicates (aliases)
            for k, names in self.duplicates.items():
                logging.warning(f"Alias detected: address {k} used by names {names}")

    # ---------------------------
    # Parser (handles := defaults and readonly marker in comment)
    # ---------------------------
    def parse_variables_file(self, filepath: str):
        """
        Parse lines like:
          Name AT %MW100: WORD := 100; // description (RO)
        Detection:
        - initial_value parsed from ':= <num>'
        - readonly detected if 'RO' or 'read-only' present in comment (case-insensitive)
        Returns list of dicts with keys name,address,dtype,description,initial_value,readonly
        """
        parsed = []
        if not os.path.exists(filepath):
            logging.error(f"Variables file not found: {filepath}")
            return parsed

        with open(filepath, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                description = ""
                if "//" in line:
                    code_part, comment = line.split("//", 1)
                    description = comment.strip()
                else:
                    code_part = line

                # remove trailing semicolon if present
                code_part = code_part.strip().rstrip(";").strip()
                initial_value = None
                readonly = False
                # detect initial ':='
                if ":=" in code_part:
                    before, after = code_part.split(":=", 1)
                    code_part = before.strip()
                    # after may contain semicolon already removed
                    try:
                        initial_value = int(after.strip())
                    except Exception:
                        initial_value = after.strip()

                # detect read-only markers in description (client said some are read-only)
                desc_lower = (description or "").lower()
                if "ro" in desc_lower.split() or "read-only" in desc_lower or "readonly" in desc_lower:
                    readonly = True

                # now parse 'Name AT %ADDR: TYPE'
                try:
                    if "AT" not in code_part or ":" not in code_part:
                        logging.error(f"Unrecognized format (skipping): {raw.strip()}")
                        continue
                    name_part, rest = code_part.split("AT", 1)
                    name = name_part.strip()
                    addr_part, dtype_part = rest.split(":", 1)
                    address = addr_part.strip()
                    dtype = dtype_part.strip().upper()
                    parsed.append({
                        "name": name,
                        "address": address,
                        "dtype": dtype,
                        "description": description,
                        "initial_value": initial_value,
                        "readonly": readonly
                    })
                except Exception as e:
                    logging.error(f"Failed to parse line: {raw.strip()} -> {e}")

        return parsed

    # ---------------------------
    # Create wrapper objects and handle aliases
    # ---------------------------
    def instantiate_wrappers(self, parsed_vars):
        """
        Create wrapper objects. If two names map to same canonical address,
        they will point to the same wrapper instance (aliasing).
        """
        self.variables = {}
        self.registry = {}
        self.duplicates = {}

        for v in parsed_vars:
            name = v["name"]
            address = v["address"]
            dtype = v["dtype"]
            desc = v["description"]
            init = v["initial_value"]
            readonly = v["readonly"]

            base, num, bit = parse_address(address)
            key = canonical_key(base, num, bit)

            # If an object already exists for this address, use it (alias)
            existing = self.registry.get(key)
                        
            
            if existing:
                self.variables[name] = existing
                self.duplicates.setdefault(key, []).append(name)

                # If alias has an initial value and main object has no value yet
                if v["initial_value"] is not None:
                    if getattr(existing, "initial_value", None) is None:
                        existing.initial_value = v["initial_value"]
                    if getattr(existing, "value", None) is None:
                        try:
                            existing.value = int(v["initial_value"])
                        except Exception:
                            existing.value = v["initial_value"]
                continue  # <-- important: skip to next var, don't return

            # create appropriate wrapper
            if dtype in ("BOOL", "BIT"):
                obj = Flag(name, address, desc)
                # add convenience properties
                obj.initial_value = init
                obj.readonly = readonly
            elif dtype == "WORD":
                obj = Word(name, address, desc)
                obj.initial_value = init
                obj.readonly = readonly
            elif dtype == "BYTE":
                obj = Byte(name, address, desc)
                obj.initial_value = init
                obj.readonly = readonly
            elif dtype == "DWORD":
                obj = DWord(name, address, desc)
                obj.initial_value = init
                obj.readonly = readonly
            elif dtype == "TIME":
                # ASSUMPTION from client: TIME -> structured timer object
                obj = TimerWrapper(name, address, desc)
                obj.initial_value = init
                obj.readonly = readonly
            else:
                # fallback to Word
                logging.warning(f"Unsupported type {dtype} for {name}, defaulting to Word")
                obj = Word(name, address, desc)
                obj.initial_value = init
                obj.readonly = readonly

            # apply initial value if present (do not prevent future reads)
            if init is not None:
                try:
                    # prefer typed assignment for Word/Byte/DWord
                    if hasattr(obj, "value"):
                        obj.value = int(init)
                    else:
                        obj.value = init
                except Exception:
                    obj.value = init

            # store object in both variables (by name) and registry (by canonical address)
            self.variables[name] = obj
            self.registry[key] = obj
            # also record the canonical name as list for duplicates detection
            self.duplicates.setdefault(key, [name])

    # ---------------------------
    # Build registry (recompute) - handy if dynamic reload needed
    # ---------------------------
    def build_address_registry(self):
        """Rebuild canonical registry and duplicate mapping from current self.variables."""
        self.registry = {}
        self.duplicates = {}
        for name, obj in self.variables.items():
            # parse the obj.address
            try:
                base, num, bit = parse_address(obj.address)
                key = canonical_key(base, num, bit)
                if key in self.registry:
                    # alias: multiple names pointing to same address
                    # ensure both names map to same object (they should)
                    # Keep registry[key] as first created object
                    # but record duplicates
                    self.duplicates.setdefault(key, [])
                    if name not in self.duplicates[key]:
                        self.duplicates[key].append(name)
                else:
                    self.registry[key] = obj
                    self.duplicates.setdefault(key, [name])
            except Exception:
                continue

    def alive(self) -> bool:
        with self._alive_lock:
            try:
                if self.client.is_open():
                    self._alive_state = True
                    self.last_alive = time.time()
                    return True
            except Exception:
                pass

    # ---------------------------
    # Connection handling with retry (client answered Q6)
    # ---------------------------
    def alive(self) -> bool:
        """
        Try to ensure the Modbus connection is open.
        Policy (client): 3 retries, then set alive to False and close.
        If called again, will attempt to reconnect.
        """
        with self._alive_lock:
            # quick return if already open
            try:
                if self.client.is_open():
                    self._alive_state = True
                    self.last_alive = time.time()
                    return True
            except Exception:
                # if is_open property missing, attempt open below
                pass

            retries = 3
            for attempt in range(1, retries + 1):
                try:
                    ok = self.client.open()
                    if ok:
                        self._alive_state = True
                        self.last_alive = time.time()
                        return True
                except Exception as e:
                    logging.warning(f"alive(): attempt {attempt} failed -> {e}")
                time.sleep(0.2)  # short pause between tries

            # after retries, mark as not alive, close client
            try:
                self.client.close()
            except Exception:
                pass
            self._alive_state = False
            return False
        
    def read_from_plc(self, base, num, bit=None):
        """Read from PLC depending on base type (MW, MB, MX, MD)."""
        if not self.alive():  # Ensure PLC connection is open
            return None

        try:
            if base == "MW":  # Word (16-bit register)
                regs = self.client.read_holding_registers(num, 1)  # Read one word
                return regs[0] if regs else None  # Return value if read succeeded

            elif base == "MB":  # Byte (half of a Word)
                regs = self.client.read_holding_registers(num // 2, 1)  # Read parent word
                if not regs:  # No data
                    return None
                word_val = regs[0]  # Extract word value
                if num % 2 == 0:  # Even index → low byte
                    return word_val & 0xFF
                else:  # Odd index → high byte
                    return (word_val >> 8) & 0xFF

            elif base == "MX":  # Bit inside a byte
                regs = self.client.read_holding_registers(num // 2, 1)  # Read parent word
                if not regs:
                    return None
                word_val = regs[0]
                byte_val = (word_val >> ((num % 2) * 8)) & 0xFF  # Select target byte
                return bool((byte_val >> bit) & 1)  # Extract bit as boolean

            elif base == "MD":  # Double word (32-bit)
                regs = self.client.read_holding_registers(num, 2)  # Read two words
                if regs and len(regs) == 2:
                    return (regs[1] << 16) | regs[0]  # Combine into 32-bit value

        except Exception as e:
            logging.error(f"PLC read failed: {e}")  # Log read error
            return None


    def write_to_plc(self, base, num, value, bit=None):
        """Write to PLC depending on base type."""
        if not self.alive():  # Ensure PLC connection is open
            return False

        try:
            if base == "MW":  # Write full 16-bit word
                return self.client.write_single_register(num, int(value))

            elif base == "MB":  # Write single byte (via read-modify-write of parent word)
                parent = num // 2  # Parent MW index
                regs = self.client.read_holding_registers(parent, 1)  # Read current word
                word_val = regs[0] if regs else 0
                if num % 2 == 0:  # Low byte
                    word_val = (word_val & 0xFF00) | (int(value) & 0xFF)
                else:  # High byte
                    word_val = (word_val & 0x00FF) | ((int(value) & 0xFF) << 8)
                return self.client.write_single_register(parent, word_val)

            elif base == "MX":  # Write single bit
                parent = num // 2  # Parent MW index
                regs = self.client.read_holding_registers(parent, 1)  # Read current word
                word_val = regs[0] if regs else 0
                byte_val = (word_val >> ((num % 2) * 8)) & 0xFF  # Extract byte
                if value:  # Set bit
                    byte_val |= (1 << bit)
                else:  # Clear bit
                    byte_val &= ~(1 << bit)
                if num % 2 == 0:  # Write back to low byte
                    word_val = (word_val & 0xFF00) | byte_val
                else:  # Write back to high byte
                    word_val = (word_val & 0x00FF) | (byte_val << 8)
                return self.client.write_single_register(parent, word_val)

            elif base == "MD":  # Write double word (32-bit)
                lo = value & 0xFFFF  # Lower 16 bits
                hi = (value >> 16) & 0xFFFF  # Upper 16 bits
                return self.client.write_multiple_registers(num, [lo, hi])

        except Exception as e:
            logging.error(f"PLC write failed: {e}")  # Log write error
            return False

    # ---------------------------
    # Read / Write API (unified)
    # ---------------------------
    def read_var(self, name):
        obj = self.variables.get(name)                # Look up wrapper object by name
        if obj is None:                                # If not defined, return None
            return None
        base, num, bit = parse_address(obj.address)    # Break down %MW / %MB / %MX / %MD into parts
        plc_val = self.read_from_plc(base, num, bit)   # Ask PLC for the live value
        if plc_val is not None:                        # If PLC returned a value
            obj.value = plc_val                        # Update wrapper with latest live value
        return obj.value                               # Return the (now updated) value
    
    def write_var(self, name, value, force: bool = False):
        """
        Write to a variable:
        - Respect readonly and := initial value rules
        - Write both locally (wrapper.value) and to the PLC
        - Keep MW <-> MB <-> MX sync logic
        """
        obj = self.variables.get(name)
        if obj is None:
            raise KeyError(f"Variable '{name}' not defined")

        # read-only protection
        if getattr(obj, "readonly", False) and not force:
            logging.warning(f"Write blocked: variable '{name}' is read-only")
            return False

        # preserve initial defaults unless force=True
        if getattr(obj, "initial_value", None) is not None and not force:
            logging.info(f"Skipping write for '{name}' (initial value present). Use force=True to override.")
            return False

        # get parsed address
        try:
            base, num, bit = parse_address(obj.address)
        except Exception as e:
            logging.error(f"Failed parsing address for {name}: {e}")
            return False

        # ---- 1. Try PLC write ----
        plc_ok = self.write_to_plc(base, num, value, bit)
        if not plc_ok:
            logging.warning(f"PLC write failed for {name}, fallback to local only")

        # ---- 2. Local update anyway (so simulation + aliases stay in sync) ----
        try:
            if hasattr(obj, "value"):
                obj.value = value
            elif hasattr(obj, "set"):
                obj.set(value)
            else:
                setattr(obj, "value", value)
        except Exception as e:
            logging.error(f"Error setting local value for {name}: {e}")

        # ---- 3. Sync related addresses ----
        with self._sync_lock:
            try:
                if base == "MW":
                    self._sync_mw_to_mb_mx(num)
                elif base == "MB":
                    self._sync_mb_to_mw(num)
                elif base == "MX":
                    self._sync_mx_to_mb_mw(num, bit)
                elif base == "MD":
                    # TODO: advanced DWORD sync if needed
                    pass
            except Exception as e:
                logging.error(f"sync after write failed: {e}")

        return plc_ok
    

    # ---------------------------
    # Synchronization helpers
    # ---------------------------
    def _get_registry_obj(self, key: str):
        """Helper to return registry object or None."""
        return self.registry.get(key)

    def _sync_mw_to_mb_mx(self, mw_num: int):
        """
        When MWn changes, update MB(2n), MB(2n+1) and corresponding MX bits.
        """
        # canonical MW key
        mw_key = canonical_key("MW", mw_num, None)
        mw_obj = self.registry.get(mw_key)
        if mw_obj is None:
            return

        # use 0 if None
        try:
            word_val = int(getattr(mw_obj, "value", 0) or 0)
        except Exception:
            word_val = 0

        low = word_val & 0xFF
        high = (word_val >> 8) & 0xFF

        mb_low_idx = 2 * mw_num
        mb_high_idx = mb_low_idx + 1

        # update MB low
        mb_low_key = canonical_key("MB", mb_low_idx, None)
        mb_high_key = canonical_key("MB", mb_high_idx, None)

        mb_low_obj = self._get_registry_obj(mb_low_key)
        if mb_low_obj:
            mb_low_obj.value = low

        mb_high_obj = self._get_registry_obj(mb_high_key)
        if mb_high_obj:
            mb_high_obj.value = high

        # update MX bits for low byte
        if mb_low_obj:
            for bit in range(8):
                mx_key = canonical_key("MX", mb_low_idx, bit)
                mx_obj = self._get_registry_obj(mx_key)
                if mx_obj:
                    bit_val = bool((low >> bit) & 1)
                    mx_obj.value = bit_val

        # update MX bits for high byte
        if mb_high_obj:
            for bit in range(8):
                mx_key = canonical_key("MX", mb_high_idx, bit)
                mx_obj = self._get_registry_obj(mx_key)
                if mx_obj:
                    bit_val = bool((high >> bit) & 1)
                    mx_obj.value = bit_val

    def _sync_mb_to_mw(self, mb_num: int):
        """
        When MB changes, recompute its sibling MB and update the parent MW value.
        MB index -> parent MW = MB_index // 2
        """
        parent_mw = mb_num // 2
        mb_low_idx = 2 * parent_mw
        mb_high_idx = mb_low_idx + 1

        mb_low_key = canonical_key("MB", mb_low_idx, None)
        mb_high_key = canonical_key("MB", mb_high_idx, None)
        mw_key = canonical_key("MW", parent_mw, None)

        low_obj = self._get_registry_obj(mb_low_key)
        high_obj = self._get_registry_obj(mb_high_key)
        low_val = int(getattr(low_obj, "value", 0) or 0) if low_obj else 0
        high_val = int(getattr(high_obj, "value", 0) or 0) if high_obj else 0

        new_word = (high_val << 8) | (low_val & 0xFF)

        mw_obj = self._get_registry_obj(mw_key)
        if mw_obj:
            mw_obj.value = new_word

    def _sync_mx_to_mb_mw(self, mb_num: int, bit: int):
        """
        When MX (bit) changes, update the MB byte bit and then parent MW.
        MX key uses MB index and bit.
        """
        mb_key = canonical_key("MB", mb_num, None)
        mb_obj = self._get_registry_obj(mb_key)
        if not mb_obj:
            # nothing to do
            return

        # recompute mb byte from all MX bits we know
        byte_val = 0
        for b in range(8):
            mx_key = canonical_key("MX", mb_num, b)
            mx_obj = self._get_registry_obj(mx_key)
            bitv = 1 if (mx_obj and getattr(mx_obj, "value", False)) else 0
            byte_val |= (bitv << b)

        mb_obj.value = byte_val
        # now push to MW
        self._sync_mb_to_mw(mb_num)

    # ---------------------------
    # Polling group manager
    # ---------------------------
    def add_polling_group(self, group_name: str, var_names: list, interval_ms: int = 500):
        """
        Create and start a polling thread for the given list of variable names.
        If group exists, it will be restarted.
        Default interval = 500 ms (client requested).
        """
        # stop existing group if present
        if group_name in self.polling_groups:
            self.stop_polling_group(group_name)

        stop_event = threading.Event()

        def poll_loop():
            logging.info(f"Polling group '{group_name}' started (interval {interval_ms} ms)")
            while not stop_event.is_set():
                # if alive and real client, we'd read actual registers here
                for name in var_names:
                    # calling read_var gives current wrapper value (dry-run)
                    val = self.read_var(name)
                    logging.debug(f"[poll:{group_name}] {name} = {val}")
                stop_event.wait(interval_ms / 1000.0)
            logging.info(f"Polling group '{group_name}' stopped")

        t = threading.Thread(target=poll_loop, daemon=True)
        t.start()

        self.polling_groups[group_name] = {"thread": t, "stop_event": stop_event,
                                          "vars": var_names, "interval_ms": interval_ms}

    def stop_polling_group(self, group_name: str):
        ent = self.polling_groups.get(group_name)
        if not ent:
            return
        ent["stop_event"].set()
        # thread is daemon; it will stop soon
        del self.polling_groups[group_name]

    # ---------------------------
    # Utility: reload variables at runtime
    # ---------------------------
    def load_variables_from_file(self, filepath: str):
        """Reload variables and rebuild registry (dynamic reload)."""
        parsed = self.parse_variables_file(filepath)
        self.instantiate_wrappers(parsed)
        self.build_address_registry()
        logging.info("Variables reloaded from file.")
