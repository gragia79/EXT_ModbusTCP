# polling/poller.py
import threading
import time
import logging
from typing import List

# you will import your ModbusWrapper
# from ext_modbus_blueprint import ModbusWrapper

class Poller:
    def __init__(self, mw, var_names: List[str], interval_ms: int = 500, unit_id: int = 1):
        """
        mw: ModbusWrapper instance
        var_names: list of variable NAMES (as in variables.txt)
        interval_ms: polling period
        unit_id: Modbus unit/slave id (if needed)
        """
        self.mw = mw
        self.var_names = var_names[:]
        self.interval_ms = interval_ms
        self.unit_id = unit_id
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logging.info(f"Poller started for {self.var_names} @ {self.interval_ms}ms")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        logging.info("Poller stopped")

    # --- helper: map wrapper address -> modbus read call info
    def _map_to_modbus(self, wrapper):
        """
        Return tuple (func, address, count)
        func: 'holding', 'input', 'coils', 'discrete'
        address: integer starting register/coil index (0-based)
        count: number of registers/coils to read

        NOTE: YOU MUST ADAPT THIS TO YOUR PLC ADDRESSING AND OFFSET RULES.
        """
        addr = wrapper.address  # example: "%MW100", "%MB6", "%MX8.0", "%IX0.0"
        base, num, bit = wrapper_addr_parse(addr)  # implement or import parse_address variant
        # Example assumptions (adjust per device):
        if base == "MW":  # holding registers
            return ("holding", num, 1)
        if base == "MB":  # bufs map to MW scaled; read as part of MW (may need special handling)
            # read parent MW (num//2) and then extract the byte
            return ("holding", num // 2, 1)
        if base in ("IX",):  # discrete inputs
            return ("discrete", num, 1)
        if base in ("MX", "QX"):  # coils (outputs)
            return ("coils", num, 1)
        if base == "MD":  # dword - read 2 holding registers
            return ("holding", num * 2, 2)
        # fallback:
        return ("holding", num, 1)

    def _run(self):
        while not self._stop.is_set():
            start = time.time()
            # prefer using mw.alive() policy (this will do the 3 retries logic)
            if not self.mw.alive():
                logging.warning("Poller: client not alive, skipping cycle")
                time.sleep(self.interval_ms / 1000.0)
                continue

            # For each var, perform read and update wrapper
            for name in self.var_names:
                with self._lock:
                    wrapper = self.mw.variables.get(name)
                    if not wrapper:
                        continue
                    func, addr, count = self._map_to_modbus(wrapper)
                    try:
                        if func == "holding":
                            # using pyModbusTCP client API
                            regs = self.mw.client.read_holding_registers(addr, count, unit=self.unit_id)
                            if regs is None:
                                continue
                            # translate regs -> value depending on wrapper type
                            val = convert_regs_to_value(wrapper, regs)  # implement mapping
                            wrapper.value = val
                        elif func == "coils":
                            coils = self.mw.client.read_coils(addr, count, unit=self.unit_id)
                            if coils:
                                wrapper.value = bool(coils[0])
                        elif func == "discrete":
                            disc = self.mw.client.read_discrete_inputs(addr, count, unit=self.unit_id)
                            if disc:
                                wrapper.value = bool(disc[0])
                        # after setting wrapper.value, sync affected addresses
                        # parse wrapper.address to call mw._sync_mw_to_mb_mx etc.
                        base, num, bit = parse_address(wrapper.address)  # import same helper
                        if base == "MW":
                            self.mw._sync_mw_to_mb_mx(num)
                        elif base == "MB":
                            self.mw._sync_mb_to_mw(num)
                        elif base == "MX":
                            self.mw._sync_mx_to_mb_mw(num, bit)
                    except Exception as e:
                        logging.exception(f"Poll read error for {name}: {e}")
            # sleep remainder
            elapsed = time.time() - start
            to_wait = max(0, self.interval_ms / 1000.0 - elapsed)
            time.sleep(to_wait)

# Helper stubs you must implement or import
def parse_address(addr):  # reuse your existing parse_address
    from ext_modbus_blueprint import parse_address as p
    return p(addr)

def wrapper_addr_parse(addr):
    return parse_address(addr)

def convert_regs_to_value(wrapper, regs):
    # basic examples:
    # Word: regs[0]
    # DWord: combine regs[0] << 16 | regs[1]
    # Flag / coil: handled in coils/discrete branch
    cls = wrapper.__class__.__name__
    if cls == "Word":
        return int(regs[0])
    if cls == "DWord":
        return (int(regs[0]) << 16) | int(regs[1])
    return int(regs[0])
