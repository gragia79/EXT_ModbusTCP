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
from polling.poller import Poller

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
      %IX0.0  -> ('IX', 0, 0)
    Returns (base, num, bit) where bit may be None
    """
    s = addr.strip()
    if s.startswith("%"):
        s = s[1:]
    s = s.upper()

    if "." in s:  # bit-address form: MX8.0 or IX0.0
        base = s[:2]            # first two letters = base
        left, bit_s = s.split(".", 1)
        num = int(left[2:])     # digits after base up to the dot
        bit = int(bit_s)
        return base, num, bit
    else:
        base = s[:2]
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
    def __init__(self, ip, port=502, unit_id=0, variable_file="variables.txt"):
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
        try:
            self.client.debug = True
        except Exception:
            pass
        self._last_plc_error = None
        
        self._client_lock = threading.RLock()  # Guards all socket I/O so it’s thread‑safe
        self._vars_lock = threading.RLock()   # protects variables/registry/duplicates modifications

        self.last_alive = None
        self._alive_state = False
        self._alive_lock = threading.Lock()
        self.variables = {}      # name -> wrapper object (Flag/Word/Byte/DWord/TimerWrapper)
        self.registry = {}       # canonical address key -> wrapper object
        self.duplicates = {}     # canonical -> [names]
        self._sync_lock = threading.RLock()  # guard to avoid recursive sync
        self.md_big_endian = False  # False = low word first (most Delta PLCs).
                                    # Set True if the real PLC expects hi word first.

        # timing / breathing space for PLC after writes (seconds)
        self.write_delay = 0.1   # legacy field (still supported)
        self.read_delay = 0.1    # delay after reads if needed

        # how long to wait after a successful write before next access (milliseconds)
        self.write_settle_ms = 80  # Graziano wants waits inside the function


        # polling groups: name -> dict { thread, interval_ms, vars, stop_event }
        self.polling_groups = {}


        # allow relative defaults for the variables file
        if variable_file and not os.path.isabs(variable_file):
            variable_file = os.path.join(os.getcwd(), variable_file)

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
        - readonly detected if 'RO', 'read-only', or 'readonly' present in comment (case-insensitive)
        OR if 'readonly' appears inline after the type in variables.txt
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
                    try:
                        initial_value = int(after.strip())
                    except Exception:
                        initial_value = after.strip()

                # detect read-only markers in description
                desc_lower = (description or "").lower()
                if (
                    "ro" in desc_lower.split()
                    or "read-only" in desc_lower
                    or "readonly" in desc_lower
                ):
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

                    # split dtype part into tokens to detect inline 'readonly'
                    dtype_tokens = dtype_part.strip().split()
                    dtype = dtype_tokens[0].upper() if dtype_tokens else ""
                    if any(tok.lower() == "readonly" for tok in dtype_tokens[1:]):
                        readonly = True

                    # 🔹 Mark IX (discrete inputs) as read-only automatically
                    addr_clean = address.strip()
                    if addr_clean.upper().startswith("%IX"):
                        readonly = True

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
    # PATCH#3 - Helper functions
    # ---------------------------
    def _set_dead(self, reason: str = ""):
        try:
            self._alive_state = False
            # try to get client last_error if available
            last_err = getattr(self.client, "last_error", None)
            self._last_plc_error = last_err
            unit = getattr(self.client, "unit_id", getattr(self, "unit_id", None))
            logging.error(
                f"Connection marked NOT ALIVE. reason='{reason}' host={self.host}:{self.port} unit={unit} last_error={last_err}"
            )
            try:
                self.client.close()
            except Exception:
                pass
        except Exception:
            pass


        
    def _set_value(self, obj, new_value):
        """Assign value and toggle 'changed' if supported by wrapper."""
        try:
            old = getattr(obj, "value", None)
            if old != new_value:
                # common pattern: wrappers may have a private flag or isChanged method
                # We just set _changed if it exists; .isChanged() will clear it later.
                try:
                    setattr(obj, "_changed", True)
                except Exception:
                    pass
            obj.value = new_value
        except Exception as e:
            logging.error(f"_set_value failed for {getattr(obj,'name','?')}: {e}")
            
            
    def _client_is_open(self):
        """
        Compatibility wrapper for pyModbusTCP/pymodbus differences in is_open.
        Returns True if the underlying socket is open, False otherwise.
        """
        is_open_attr = getattr(self.client, "is_open", None)
        try:
            # Callable style (method)
            return is_open_attr() if callable(is_open_attr) else bool(is_open_attr)
        except Exception:
            # Fallback: check private socket handle
            return getattr(self.client, "_client_socket", None) is not None
        
        
    def _extract_registers(self, read_res):
        """
        Accept many forms from pyModbusTCP / pymodbus variations:
        - None
        - list of ints
        - object with .registers
        Return list or None
        """
        if read_res is None:
            return None
        if hasattr(read_res, "registers"):
            try:
                return list(read_res.registers)
            except Exception:
                return None
        if isinstance(read_res, (list, tuple)):
            return list(read_res)
        return None  # fallback
    
    
    def _extract_bits(self, read_res):
        """
        Normalize discrete/coil results:
        - None -> None
        - object with .bits -> list(bits)
        - list/tuple -> list
        """
        if read_res is None:
            return None
        if hasattr(read_res, "bits"):
            try:
                return list(read_res.bits)
            except Exception:
                return None
        if isinstance(read_res, (list, tuple)):
            return list(read_res)
        return None


        
    def _write_ok(self, write_res):
        """Normalise different write result types to a boolean success/fail."""
        if write_res is None:
            return False
        # pymodbus style: object with isError()
        if hasattr(write_res, "isError"):
            try:
                return not write_res.isError()
            except Exception:
                return False
        # pyModbusTCP style: True/False
        try:
            return bool(write_res)
        except Exception:
            return False
        
    def identify(self):
        """
        Try to read device identification (if client supports it).
        Returns info or None.
        """
        try:
            with self._client_lock:
                if hasattr(self.client, "read_device_identification"):
                    return self.client.read_device_identification()
        except Exception as e:
            logging.debug(f"identify() failed: {e}")
        return None

    def is_changed(self, name: str) -> bool:
        """
        Return True if the variable has changed since the last polling cycle.
        Delegates to the underlying wrapper's .isChanged() if available.
        """
        with self._vars_lock:
            obj = self.variables.get(name)

        if obj is None:
            logging.warning(f"is_changed: Variable '{name}' not found")
            return False

        if hasattr(obj, "isChanged"):
            try:
                return obj.isChanged()
            except Exception as e:
                logging.error(f"is_changed failed for {name}: {e}")
                return False

        return False

        
    # ---------------------------
    # Create wrapper objects and handle aliases
    # ---------------------------
    
    def instantiate_wrappers(self, parsed_vars, replace: bool = True):
        """
        Create wrapper objects. If two names map to same canonical address,
        they will point to the same wrapper instance (aliasing).

        If replace=True the function will reset self.variables/self.registry (used at startup).
        If replace=False it will add to the existing registry (used for on-the-fly variables).
        """
        with self._vars_lock:
            if replace:
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

                # allow a marker to avoid duplicate auto-expansion
                auto_generated = v.get("auto_generated", False)

                base, num, bit = parse_address(address)
                key = canonical_key(base, num, bit)

                # If an object already exists for this address, use it (alias)
                existing = self.registry.get(key)
                if existing:
                    self.variables[name] = existing
                    self.duplicates.setdefault(key, [])
                    if name not in self.duplicates[key]:
                        self.duplicates[key].append(name)
                    if init is not None:
                        if getattr(existing, "initial_value", None) is None:
                            existing.initial_value = init
                        if getattr(existing, "value", None) is None:
                            try:
                                existing.value = int(init)
                            except Exception:
                                existing.value = init
                    continue

                # create appropriate wrapper
                if dtype in ("BOOL", "BIT"):
                    obj = Flag(name, address, desc)
                elif dtype == "WORD":
                    obj = Word(name, address, desc)
                elif dtype == "BYTE":
                    obj = Byte(name, address, desc)
                elif dtype == "DWORD":
                    obj = DWord(name, address, desc)
                elif dtype == "TIME":
                    obj = TimerWrapper(name, address, desc)
                else:
                    logging.warning(f"Unsupported type {dtype} for {name}, defaulting to Word")
                    obj = Word(name, address, desc)

                obj.initial_value = init
                obj.readonly = readonly
                if init is not None:
                    try:
                        if hasattr(obj, "value"):
                            obj.value = int(init)
                        else:
                            obj.value = init
                    except Exception:
                        obj.value = init

                self.variables[name] = obj
                self.registry[key] = obj
                self.duplicates.setdefault(key, [name])

                # -----------------------------------------------------
                # 🔹 Auto-expansion logic (Word → Byte → Bit)
                # -----------------------------------------------------
                if not auto_generated:
                    if dtype == "WORD":
                        low_byte = num * 2
                        high_byte = num * 2 + 1
                        aliases = [
                            {
                                "name": f"{name}_LOW",
                                "address": f"%MB{low_byte}",
                                "dtype": "BYTE",
                                "description": f"Auto low byte of {name}",
                                "initial_value": None,
                                "readonly": readonly,
                                "auto_generated": True,
                            },
                            {
                                "name": f"{name}_HIGH",
                                "address": f"%MB{high_byte}",
                                "dtype": "BYTE",
                                "description": f"Auto high byte of {name}",
                                "initial_value": None,
                                "readonly": readonly,
                                "auto_generated": True,
                            },
                        ]
                        logging.info(f"Auto-expanded {name} (%MW{num}) → %MB{low_byte}, %MB{high_byte}")
                        self.instantiate_wrappers(aliases, replace=False)

                    elif dtype == "BYTE":
                        bit_base = num
                        aliases = []
                        for b in range(8):
                            aliases.append({
                                "name": f"{name}_BIT{b}",
                                "address": f"%MX{bit_base}.{b}",
                                "dtype": "BOOL",
                                "description": f"Auto bit {b} of {name}",
                                "initial_value": None,
                                "readonly": readonly,
                                "auto_generated": True,
                            })
                        logging.info(f"Auto-expanded {name} (%MB{num}) → %MX{num}.0–%MX{num}.7")
                        self.instantiate_wrappers(aliases, replace=False)

                # -----------------------------------------------------
                # 🔹 Sync new expansions to parent (optional but cleaner)
                # -----------------------------------------------------
                if dtype == "WORD" and init is not None:
                    try:
                        self._sync_mw_to_mb_mx(num)
                    except Exception as e:
                        logging.debug(f"Initial sync failed for MW{num}: {e}")


    # def instantiate_wrappers(self, parsed_vars, replace: bool = True):
    #     """
    #     Create wrapper objects. If two names map to same canonical address,
    #     they will point to the same wrapper instance (aliasing).

    #     If replace=True the function will reset self.variables/self.registry (used at startup).
    #     If replace=False it will add to the existing registry (used for on-the-fly variables).
    #     """
    #     with self._vars_lock:
    #         if replace:
    #             self.variables = {}
    #             self.registry = {}
    #             self.duplicates = {}

    #         for v in parsed_vars:
    #             name = v["name"]
    #             address = v["address"]
    #             dtype = v["dtype"]
    #             desc = v["description"]
    #             init = v["initial_value"]
    #             readonly = v["readonly"]

    #             base, num, bit = parse_address(address)
    #             key = canonical_key(base, num, bit)

    #             # If an object already exists for this address, use it (alias)
    #             existing = self.registry.get(key)

    #             if existing:
    #                 # alias: reuse existing object, add name mapping
    #                 self.variables[name] = existing
    #                 self.duplicates.setdefault(key, [])
    #                 if name not in self.duplicates[key]:
    #                     self.duplicates[key].append(name)

    #                 # If alias has an initial value and main object has no value yet
    #                 if init is not None:
    #                     if getattr(existing, "initial_value", None) is None:
    #                         existing.initial_value = init
    #                     if getattr(existing, "value", None) is None:
    #                         try:
    #                             existing.value = int(init)
    #                         except Exception:
    #                             existing.value = init
    #                 continue

    #             # create appropriate wrapper
    #             if dtype in ("BOOL", "BIT"):
    #                 obj = Flag(name, address, desc)
    #             elif dtype == "BYTE":
    #                 obj = Byte(name, address, desc)
    #             elif dtype == "DWORD":
    #                 obj = DWord(name, address, desc)
    #             elif dtype == "TIME":
    #                 obj = TimerWrapper(name, address, desc)  
                    
                    
    #             # with initial sync 
    #             elif dtype == "WORD":
    #                 obj = Word(name, address, desc)

    #                 # metadata
    #                 obj.initial_value = init
    #                 obj.readonly = readonly

    #                 # apply initial value if present
    #                 if init is not None:
    #                     try:
    #                         obj.value = int(init)
    #                     except Exception:
    #                         obj.value = init

    #                 # store object in both variables and registry
    #                 self.variables[name] = obj
    #                 self.registry[key] = obj
    #                 self.duplicates.setdefault(key, [name])

    #                 # 🔹 Auto-expand Word into Byte + Bit aliases
    #                 try:
    #                     base, num, bit = parse_address(address)
    #                     if base == "MW":
    #                         low_b = num * 2
    #                         high_b = low_b + 1

    #                         aliases = [
    #                             (f"{name}_LowByte", f"%MB{low_b}", "BYTE"),
    #                             (f"{name}_HighByte", f"%MB{high_b}", "BYTE"),
    #                         ]
    #                         for b in range(8):
    #                             aliases.append((f"{name}_LowBit{b}", f"%MX{low_b}.{b}", "BOOL"))
    #                             aliases.append((f"{name}_HighBit{b}", f"%MX{high_b}.{b}", "BOOL"))

    #                         for alias_name, alias_addr, alias_dtype in aliases:
    #                             parsed_alias = {
    #                                 "name": alias_name,
    #                                 "address": alias_addr,
    #                                 "dtype": alias_dtype,
    #                                 "description": f"Auto-alias from {name}",
    #                                 "initial_value": None,
    #                                 "readonly": False,
    #                             }
    #                             self.instantiate_wrappers([parsed_alias], replace=False)

    #                         # 🔹 Push initial value to aliases immediately
    #                         if init is not None:
    #                             self._sync_mw_to_mb_mx(num)
    #                 except Exception as e:
    #                     logging.error(f"Failed to expand Word {name} -> {e}")
                    
    #             # without initial sync 
    #             # elif dtype == "WORD":
    #             #     obj = Word(name, address, desc)

    #             #     # 🔹 Auto-expand Word into Byte + Bit aliases
    #             #     try:
    #             #         base, num, bit = parse_address(address)
    #             #         if base == "MW":
    #             #             # Each MW<n> corresponds to MB<2n> (low byte) and MB<2n+1> (high byte)
    #             #             low_b = num * 2
    #             #             high_b = low_b + 1
                            
    #             #             # Generate Byte wrappers
    #             #             aliases = [
    #             #                 (f"{name}_LowByte", f"%MB{low_b}", "BYTE"),
    #             #                 (f"{name}_HighByte", f"%MB{high_b}", "BYTE"),
    #             #             ]

    #             #             # Generate Bit wrappers (0–7 each byte)
    #             #             for b in range(8):
    #             #                 aliases.append((f"{name}_LowBit{b}", f"%MX{low_b}.{b}", "BOOL"))
    #             #                 aliases.append((f"{name}_HighBit{b}", f"%MX{high_b}.{b}", "BOOL"))

    #             #             # Recursively instantiate these aliases as extra parsed vars
    #             #             for alias_name, alias_addr, alias_dtype in aliases:
    #             #                 parsed_alias = {
    #             #                     "name": alias_name,
    #             #                     "address": alias_addr,
    #             #                     "dtype": alias_dtype,
    #             #                     "description": f"Auto-alias from {name}",
    #             #                     "initial_value": None,
    #             #                     "readonly": False,
    #             #                 }
    #             #                 # Reuse same logic for adding
    #             #                 self.instantiate_wrappers([parsed_alias], replace=False)
                    
    #                 # except Exception as e:
    #                 #     logging.error(f"Failed to expand Word {name} -> {e}")
                
    #             else:
    #                 logging.warning(f"Unsupported type {dtype} for {name}, defaulting to Word")
    #                 obj = Word(name, address, desc)

    #             # metadata
    #             obj.initial_value = init
    #             obj.readonly = readonly

    #             # apply initial value if present (do not prevent future reads)
    #             if init is not None:
    #                 try:
    #                     if hasattr(obj, "value"):
    #                         obj.value = int(init)
    #                     else:
    #                         obj.value = init
    #                 except Exception:
    #                     obj.value = init

    #             # store object in both variables (by name) and registry (by canonical address)
    #             self.variables[name] = obj
    #             self.registry[key] = obj
    #             self.duplicates.setdefault(key, [name])


    # ---------------------------
    # Build registry (recompute) - handy if dynamic reload needed
    # ---------------------------
    
    def build_address_registry(self):
        # Rebuild canonical registry and duplicate mapping from current self.variables.
        with self._vars_lock:
            self.registry = {}
            self.duplicates = {}
            for name, obj in self.variables.items():
                # parse the obj.address
                try:
                    base, num, bit = parse_address(obj.address)
                    key = canonical_key(base, num, bit)
                    if key in self.registry:
                        # alias: multiple names pointing to same object
                        self.duplicates.setdefault(key, [])
                        if name not in self.duplicates[key]:
                            self.duplicates[key].append(name)
                    else:
                        self.registry[key] = obj
                        self.duplicates.setdefault(key, [name])
                except Exception:
                    continue


    # ---------------------------
    # Connection handling with retry (client answered Q6)
    # ---------------------------
        
    def alive(self) -> bool:
        """
        Fast Modbus connection status check.

        - Returns True if client is open and responsive.
        - Returns False immediately if not.
        - Does NOT block, does NOT retry.

        Poller will use this: if False, it skips silently.
        Manual reads/writes will raise if alive() is False.
        """
        with self._alive_lock:
            try:
                if self._client_is_open():
                    self._alive_state = True
                    self.last_alive = time.time()
                    return True
            except Exception:
                pass

            # mark as not alive quickly
            self._alive_state = False
            return False


    def connect(self, retries: int = 3, retry_delay: float = 1.0) -> bool:
        """
        Try to (re)connect with optional retries.

        - retries > 0 : try N times, return True if connected, False if not.
        - retries = 0 : try forever until connected (blocking).
        - retry_delay : seconds between attempts.

        Use this from the main program when you want to (re)connect.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                ok = self.client.open()
                if ok and self._client_is_open():
                    self._alive_state = True
                    self.last_alive = time.time()
                    logging.info(f"Connected to {self.host}:{self.port}")
                    return True
            except Exception as e:
                logging.warning(f"connect(): attempt {attempt} failed -> {e}")

            if retries > 0 and attempt >= retries:
                self._alive_state = False
                return False

            time.sleep(retry_delay)


        
    def last_error(self):
        """Return the last PLC error stored (or None if none)."""
        return self._last_plc_error
    
    # ---------------------------
    # Read and Write low-level functions
    # ---------------------------
    
    def read_from_plc(self, base, num, bit=None):
        """Read from PLC depending on base type (MW, MB, MX, MD, IX)."""

        if not self.alive():  # Ensure PLC connection is open
            return None

        try:
            # --- MW (Word: 16-bit register) ---
            if base == "MW":
                with self._client_lock:
                    regs_raw = self.client.read_holding_registers(num, 1)
                regs = self._extract_registers(regs_raw)
                if not regs:
                    self._set_dead(f"read MW{num} failed")
                    return None
                return regs[0]

            # --- MB (Byte: half of a Word) ---
            elif base == "MB":
                with self._client_lock:
                    regs_raw = self.client.read_holding_registers(num // 2, 1)
                regs = self._extract_registers(regs_raw)
                if not regs:
                    self._set_dead(f"read MB{num} failed")
                    return None
                word_val = regs[0]
                return (word_val & 0xFF) if num % 2 == 0 else ((word_val >> 8) & 0xFF)

            # --- MX (Bit inside a Byte) ---
            elif base == "MX":
                with self._client_lock:
                    regs_raw = self.client.read_holding_registers(num // 2, 1)
                regs = self._extract_registers(regs_raw)
                if not regs:
                    self._set_dead(f"read MX{num}.{bit} failed")
                    return None
                word_val = regs[0]
                byte_val = (word_val >> ((num % 2) * 8)) & 0xFF
                return bool((byte_val >> bit) & 1)

            # --- MD (Double Word: 32-bit) ---
            elif base == "MD":
                with self._client_lock:
                    regs_raw = self.client.read_holding_registers(num, 2)
                regs = self._extract_registers(regs_raw)
                if not regs or len(regs) != 2:
                    self._set_dead(f"read MD{num} failed")
                    return None
                if getattr(self, "md_big_endian", False):
                    return (regs[0] << 16) | regs[1]  # hi, lo
                else:
                    return (regs[1] << 16) | regs[0]  # lo, hi (default)

            # --- IX (Discrete input: read-only bit) ---
            elif base == "IX":
                with self._client_lock:
                    bits_raw = self.client.read_discrete_inputs(num, 1)
                bits = self._extract_bits(bits_raw)
                if not bits:
                    self._set_dead(f"read IX{num} failed")
                    return None
                return bool(bits[0])

        except Exception as e:
            logging.error(f"PLC read failed: {e}")
            self._set_dead(f"exception in read {base}{num}")
            return None
        

    def write_to_plc(self, base, num, value, bit=None):
        """
        Write to PLC depending on base type, with debug logging of results.
        - Uses _write_ok() to validate results across Modbus client versions
        - Marks connection dead on any hard failure
        - Waits self.write_settle_ms after success to let PLC settle
        - Returns True on confirmed success, False otherwise
        """
        if not self.alive():  # Bail if PLC is not currently connected/alive
            return False

        try:
            # --- MW (full 16-bit word) ---
            if base == "MW":
                with self._client_lock:
                    res_raw = self.client.write_single_register(num, int(value))
                logging.debug(f"write_single_register({num}, {int(value)}) -> {res_raw}")
                if not self._write_ok(res_raw):
                    self._set_dead(f"write MW{num} failed")
                    return False
                time.sleep(self.write_settle_ms / 1000.0)
                return True

            # --- MB (single byte within a word) ---
            elif base == "MB":
                parent = num // 2
                with self._client_lock:
                    regs_raw = self.client.read_holding_registers(parent, 1)
                regs = self._extract_registers(regs_raw) or [0]
                word_val = regs[0]
                # Modify only the targeted byte
                if num % 2 == 0:   # Low byte
                    word_val = (word_val & 0xFF00) | (int(value) & 0xFF)
                else:              # High byte
                    word_val = (word_val & 0x00FF) | ((int(value) & 0xFF) << 8)
                with self._client_lock:
                    res_raw = self.client.write_single_register(parent, word_val)
                logging.debug(f"write_single_register({parent}, {word_val}) [MB] -> {res_raw}")
                if not self._write_ok(res_raw):
                    self._set_dead(f"write MB{num} failed")
                    return False
                time.sleep(self.write_settle_ms / 1000.0)
                return True

            # --- MX (single bit within a byte) ---
            elif base == "MX":
                parent = num // 2
                with self._client_lock:
                    regs_raw = self.client.read_holding_registers(parent, 1)
                regs = self._extract_registers(regs_raw) or [0]
                word_val = regs[0]
                byte_val = (word_val >> ((num % 2) * 8)) & 0xFF
                if value:
                    byte_val |= (1 << bit)
                else:
                    byte_val &= ~(1 << bit)
                if num % 2 == 0:   # Low byte
                    word_val = (word_val & 0xFF00) | byte_val
                else:              # High byte
                    word_val = (word_val & 0x00FF) | (byte_val << 8)
                with self._client_lock:
                    res_raw = self.client.write_single_register(parent, word_val)
                logging.debug(f"write_single_register({parent}, {word_val}) [MX] -> {res_raw}")
                if not self._write_ok(res_raw):
                    self._set_dead(f"write MX{num}.{bit} failed")
                    return False
                time.sleep(self.write_settle_ms / 1000.0)
                return True

            # --- MD (full 32-bit double word) ---
            elif base == "MD":
                lo = value & 0xFFFF
                hi = (value >> 16) & 0xFFFF
                regs = [hi, lo] if getattr(self, "md_big_endian", False) else [lo, hi]
                with self._client_lock:
                    res_raw = self.client.write_multiple_registers(num, regs)
                logging.debug(f"write_multiple_registers({num}, {regs}) [MD] -> {res_raw}")
                if not self._write_ok(res_raw):
                    self._set_dead(f"write MD{num} failed")
                    return False
                time.sleep(self.write_settle_ms / 1000.0)
                return True

        except Exception as e:
            logging.error(f"PLC write failed: {e}")
            self._set_dead(f"exception in write {base}{num}")
            return False
        

    # ---------------------------
    # Read / Write API (unified)
    # ---------------------------
    
    def read_var(self, name):
        """
        Read a variable by name:
        - Looks up the wrapper object
        - Reads from PLC if connected
        - Updates the wrapper's value via _set_value()
        - Leaves local value untouched if PLC read fails (returns None)
        - Optional: small pause after read if self.read_delay > 0
        """
        if not self.alive():
            raise ConnectionError("PLC offline (alive=False)")

        
        with self._vars_lock:
            obj = self.variables.get(name)  # Thread-safe lookup
        if obj is None:                     # Not defined → nothing to do
            return None

        base, num, bit = parse_address(obj.address)    # Break down %MW / %MB / %MX / %MD
        plc_val = self.read_from_plc(base, num, bit)   # Try to get live value from PLC

        if plc_val is None:                            # Read failed
            return None                                # Caller sees None → can detect failure

        self._set_value(obj, plc_val)                  # Update wrapper & mark changed if needed

        # 🔹 Optional read delay to reduce load when looping many reads
        try:
            if getattr(self, "read_delay", 0):
                time.sleep(self.read_delay)
        except Exception:
            pass

        return obj.value                               # Return the latest value in the wrapper

    def write_var(self, name, value, force: bool = False):
        """
        Write to a variable:
        - Respects readonly and := initial value rules
        - Sends to PLC first; only updates local object if PLC confirms success
        - Keeps MW <-> MB <-> MX sync logic
        """
        if not self.alive():
            raise ConnectionError("PLC offline (alive=False)")
        
        with self._vars_lock:
            obj = self.variables.get(name)             # Thread-safe lookup
        if obj is None:
            raise KeyError(f"Variable '{name}' not defined")  # Invalid variable name

        # --- 1. Guard: read-only variable ---
        if getattr(obj, "readonly", False) and not force:
            logging.warning(f"Write blocked: variable '{name}' is read-only")
            return False

        # --- 2. Guard: has initial value (:=) and not forcing ---
        if getattr(obj, "initial_value", None) is not None and not force:
            logging.info(f"Skipping write for '{name}' (initial value present). Use force=True to override.")
            return False

        # --- 3. Parse Modbus address ---
        try:
            base, num, bit = parse_address(obj.address)
        except Exception as e:
            logging.error(f"Failed parsing address for {name}: {e}")
            return False

        # --- 4. Guard: IX discrete inputs are read-only ---
        if base == "IX":
            logging.warning(f"Write blocked: '{name}' is IX (discrete input) and read-only.")
            return False

        # --- 5. Attempt PLC write ---
        plc_ok = self.write_to_plc(base, num, value, bit)

        if not plc_ok:
            # PLC refused/failed the write — do not touch local value
            logging.warning(f"PLC write failed for {name}")
            return False  # Will be refreshed by polling on next read

        # --- 6. PLC write succeeded: update local object & mark changed ---
        self._set_value(obj, value)

        # --- 7. Sync related addresses so aliases stay in sync ---
        with self._sync_lock:
            try:
                if base == "MW":
                    self._sync_mw_to_mb_mx(num)
                elif base == "MB":
                    self._sync_mb_to_mw(num)
                elif base == "MX":
                    self._sync_mx_to_mb_mw(num, bit)
                elif base == "MD":
                    pass  # TODO: advanced DWORD sync if needed
            except Exception as e:
                logging.error(f"sync after write failed: {e}")

        return True  # Success

    # ---------------------------
    # Synchronization helpers
    # ---------------------------
    def _get_registry_obj(self, key: str):
        """Thread-safe return of registry object or None."""
        with self._vars_lock:
            return self.registry.get(key)


    def _sync_mw_to_mb_mx(self, mw_num: int):
        """
        When MWn changes, update MB(2n), MB(2n+1) and corresponding MX bits.
        """
        # canonical MW key
        mw_key = canonical_key("MW", mw_num, None)
        mw_obj = self._get_registry_obj(mw_key)

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
        

    def add_variable(self, name, address, dtype,
                    description: str = "", initial_value=None, readonly: bool = None):
        """
        Dynamically declare a variable at runtime (on-the-fly).
        Behaves like entries parsed from variables.txt.
        replace=False ensures we add without clearing existing registry.
        """
        if readonly is None:
            # Auto-mark IX (discrete inputs) as read-only
            readonly = address.strip().upper().startswith("%IX")

        parsed_like = [{
            "name": name,
            "address": address,
            "dtype": dtype.upper(),
            "description": description or "",
            "initial_value": initial_value,
            "readonly": readonly
        }]

        # Thread-safe add-on-the-fly (do not replace existing registry)
        with self._vars_lock:
            self.instantiate_wrappers(parsed_like, replace=False)
            self.build_address_registry()

        logging.info(f"On-the-fly variable added: {name} -> {address} ({dtype})")        


    def _read_with_retries(self, name: str, retries: int = 0):
        """
        Try reading a variable up to 'retries'+1 times.
        Returns value or None if all tries fail.
        """
        tries = max(0, int(retries)) + 1
        for i in range(tries):
            val = self.read_var(name)
            if val is not None:
                return val
            time.sleep(0.1)  # small spacing between attempts
        return None
    
    
    # ---------------------------
    # Utility: reload variables at runtime
    # ---------------------------
    def load_variables_from_file(self, filepath: str):
        """Reload variables and rebuild registry (dynamic reload)."""
        parsed = self.parse_variables_file(filepath)
        self.instantiate_wrappers(parsed)
        self.build_address_registry()
        logging.info("Variables reloaded from file.")


    # ---------------------------
    # Polling group manager
    # ---------------------------
    
    def add_polling_group(self, group_name, var_names, interval_ms=1000, max_cycles=0, per_read_retries=0):
        # Stop existing group if present
        if group_name in self.polling_groups:
            try:
                self.polling_groups[group_name].stop()
            except Exception:
                pass

        pg = Poller(self, var_names, interval_ms=interval_ms, unit_id=self.client.unit_id,
                    max_cycles=max_cycles, per_read_retries=per_read_retries)
        self.polling_groups[group_name] = pg

        # Auto-start only for infinite (Graziano's rule): 0 means auto-start
        if max_cycles == 0:
            pg.start()

        logging.info(
            f"Polling group '{group_name}' created with {len(var_names)} vars "
            f"(interval={interval_ms} ms, max_cycles={max_cycles}, retries={per_read_retries})"
        )
        return pg
    
