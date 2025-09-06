# polling/poller.py
import threading
import time
import logging
from typing import List

# Helper stubs you must implement or import (if not already present)
def parse_address(addr):  # reuse your existing parse_address
    from ext_modbus_blueprint import parse_address as p
    return p(addr)

def wrapper_addr_parse(addr):
    return parse_address(addr)

def convert_regs_to_value(wrapper, regs):
    cls = wrapper.__class__.__name__
    if cls == "Word":
        return int(regs[0])
    if cls == "DWord":
        return (int(regs[0]) << 16) | int(regs[1])
    return int(regs[0])

class Poller:
    def __init__(
        self,
        mw,
        var_names: List[str],
        interval_ms: int = 500,
        unit_id: int = 1,
        max_cycles: int = 0,
        per_read_retries: int = 0,
    ):
        """
        mw: ModbusWrapper instance
        var_names: list of variable NAMES (as in variables.txt)
        interval_ms: polling period in milliseconds
        unit_id: Modbus unit/slave id (if needed)
        max_cycles: 0 = run forever; >0 run that many cycles then stop
        per_read_retries: pass-through retry count for each read (optional)
        """
        self.mw = mw
        self.var_names = var_names[:]
        self.interval_ms = int(interval_ms)
        self.unit_id = unit_id
        self.max_cycles = int(max_cycles)
        self.per_read_retries = int(per_read_retries)
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
            # join but don't block forever
            self._thread.join(timeout=1.0)
        logging.info("Poller stopped")
        

    def _map_to_modbus(self, wrapper):
        # same mapping you had — keep unchanged
        addr = wrapper.address
        base, num, bit = wrapper_addr_parse(addr)
        if base == "MW":
            return ("holding", num, 1)
        if base == "MB":
            return ("holding", num // 2, 1)
        if base in ("IX",):
            return ("discrete", num, 1)
        if base in ("MX", "QX"):
            return ("coils", num, 1)
        if base == "MD":
            return ("holding", num * 2, 2)
        return ("holding", num, 1)

    def _run(self):
        logging.info(
            f"Poller loop started for {self.var_names} (interval={self.interval_ms}ms, max_cycles={self.max_cycles}, retries={self.per_read_retries})"
        )
        
        cycles = 0
        while not self._stop.is_set():
            if self.max_cycles > 0 and cycles >= self.max_cycles:
                break
            start = time.time()

            
            if not self.mw.alive():
                logging.warning("Poller: PLC not alive, skipping cycle")
                if self._stop.wait(self.interval_ms / 1000.0):
                    break
                continue

            

            for name in self.var_names:
                with self._lock:
                    wrapper = self.mw.variables.get(name)
                if not wrapper:
                    logging.debug(f"Poller: variable {name} not found, skipping")
                    continue

                # Option A: use ModbusWrapper's read retries (preferred, consistent)
                try:
                    val = None
                    # prefer calling wrapper-level read with retries if available:
                    if hasattr(self.mw, "_read_with_retries"):
                        val = self.mw._read_with_retries(name, self.per_read_retries)
                    else:
                        # fallback: direct read + convert (legacy behaviour)
                        func, addr, count = self._map_to_modbus(wrapper)
                        if func == "holding":
                            regs = self.mw.client.read_holding_registers(addr, count, unit=self.unit_id)
                            if regs is None:
                                val = None
                            else:
                                val = convert_regs_to_value(wrapper, regs)
                                # set local wrapper value
                                wrapper.value = val
                        elif func == "coils":
                            coils = self.mw.client.read_coils(addr, count, unit=self.unit_id)
                            val = bool(coils[0]) if coils else None
                            if val is not None:
                                wrapper.value = val
                        elif func == "discrete":
                            disc = self.mw.client.read_discrete_inputs(addr, count, unit=self.unit_id)
                            val = bool(disc[0]) if disc else None
                            if val is not None:
                                wrapper.value = val

                    logging.debug(f"[poll] {name} = {val}")
                except Exception as e:
                    logging.exception(f"Poll read error for {name}: {e}")

            cycles += 1
            # sleep remainder or until stop event
            elapsed = time.time() - start
            to_wait = max(0, self.interval_ms / 1000.0 - elapsed)
            if self._stop.wait(to_wait):
                break

        logging.info(f"Poller loop finished (cycles={cycles})")
