# test_2.py
# Exhaustive Modbus diagnostics for Delta DVP-style PLCs (live or simulator)
# - Tries multiple address translations (raw index, +D-offset 4096, +Delta "4xxxx" style)
# - Tries holding/coils/discrete/MD reads
# - Detailed per-attempt logging and exceptions
# - Non-destructive by default (writes disabled); enable writes manually

import time
import traceback
import logging
from pyModbusTCP.client import ModbusClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------------- CONFIG ----------------
PLC_HOST = "192.168.1.22"   # change to 127.0.0.1 for simulator
PLC_PORT = 502              # 1502 for simulator; 502 for real PLC
UNIT_IDS_TO_TRY = [0, 1]    # Graziano confirmed 1, but we also try 0
SLEEP = 0.5                 # breathing space between operations (seconds)
DO_WRITES = False           # WARNING: set True ONLY if you understand effects on real PLC
# ---------------------------------------

# Variables to check (same as your variables.txt semantics)
CHECKS = {
    "DubbleWord (MD0)": ("MD", 0),
    "Word2 (MW2)": ("MW", 2),
    "Byte6 (MB6)": ("MB", 6),
    "Flag80 (MX8.0)": ("MX", 8, 0),
    "EmergenzaImpianto (IX0.0)": ("IX", 0, 0),
    "Registro (MW100)": ("MW", 100),
    "Preset (MW100 :=100)": ("MW", 100),
    "TimCorrente (MW200 - TIME)": ("MW", 200),
}

# Address translation candidates to try
ADDRESS_OFFSETS = [
    0,
    4096,    # Delta D registers mapping (D0 -> 4096)
    28110,   # sometimes seen in older code
    40000,   # generic "4xxxx" style offset
]

def connect_client(unit_id):
    c = ModbusClient(host=PLC_HOST, port=PLC_PORT, unit_id=unit_id, auto_open=True, auto_close=False)
    try:
        c.debug = True
    except Exception:
        pass
    return c

def safe_sleep():
    time.sleep(SLEEP)

def try_read_holding(c, addr, count=1):
    try:
        r = c.read_holding_registers(addr, count)
        if r is None:
            return f"None (last_error={c.last_error})"
        return r
    except Exception as e:
        return f"EXC: {repr(e)}\n{traceback.format_exc()}"

def try_read_coils(c, addr, count=1):
    try:
        r = c.read_coils(addr, count)
        if r is None:
            return f"None (last_error={c.last_error})"
        return r
    except Exception as e:
        return f"EXC: {repr(e)}\n{traceback.format_exc()}"

def try_read_discrete(c, addr, count=1):
    try:
        r = c.read_discrete_inputs(addr, count)
        if r is None:
            return f"None (last_error={c.last_error})"
        return r
    except Exception as e:
        return f"EXC: {repr(e)}\n{traceback.format_exc()}"

def try_write_single_register(c, addr, val):
    try:
        r = c.write_single_register(addr, int(val))
        if r is None:
            return f"None (last_error={c.last_error})"
        return r
    except Exception as e:
        return f"EXC: {repr(e)}\n{traceback.format_exc()}"

def try_write_single_coil(c, addr, val):
    try:
        r = c.write_single_coil(addr, bool(val))
        if r is None:
            return f"None (last_error={c.last_error})"
        return r
    except Exception as e:
        return f"EXC: {repr(e)}\n{traceback.format_exc()}"

def interpret_result(obj):
    if obj is None:
        return "None"
    if isinstance(obj, str):
        return obj
    if hasattr(obj, "registers"):
        return f"Registers: {obj.registers}"
    if isinstance(obj, list):
        return f"List: {obj}"
    if hasattr(obj, "bits"):
        return f"Bits: {obj.bits}"
    return repr(obj)

def run_tests():
    print("\n=== MODBUS DIAGNOSTIC TEST 2 START ===\n")
    print(f"Target PLC: {PLC_HOST}:{PLC_PORT}  units={UNIT_IDS_TO_TRY}\n")

    for unit in UNIT_IDS_TO_TRY:
        print("-" * 60)
        print(f"Testing unit_id = {unit}")
        c = connect_client(unit)
        try:
            ok = c.open()
        except Exception as e:
            logging.error("open() raised: %s", e)
            ok = False
        print("open() ->", ok)
        safe_sleep()
        print(f"Connected to {PLC_HOST}:{PLC_PORT}, unit_id={unit}, is_open={c.is_open()}\n")

        # Quick holding health check
        print("-- quick holding read 0..9 --")
        hr = try_read_holding(c, 0, 10)
        print("read_holding(0,10) ->", interpret_result(hr))
        safe_sleep()

        # Quick coils health check
        print("\n-- quick coils read 0..15 --")
        coils = try_read_coils(c, 0, 16)
        print("read_coils(0,16) ->", interpret_result(coils))
        safe_sleep()

        # Detailed checks
        print("\n-- detailed checks for variables.txt items --")
        summary = {}
        for label, info in CHECKS.items():
            kind = info[0]
            num = info[1]
            bit = info[2] if len(info) > 2 else None
            print(f"\n{label} ({kind} {num}{'.'+str(bit) if bit is not None else ''})")
            results = []
            if kind == "MW":
                r = try_read_holding(c, num, 1)
                results.append(("holding_raw", num, interpret_result(r)))
            elif kind == "MD":
                r = try_read_holding(c, num, 2)
                results.append(("holding_raw_md", num, interpret_result(r)))
            elif kind in ("MB", "MX"):
                parent = num // 2
                r = try_read_holding(c, parent, 1)
                results.append(("holding_parent_raw", parent, interpret_result(r)))
            elif kind == "IX":
                r = try_read_discrete(c, num, 1)
                results.append(("discrete_raw", num, interpret_result(r)))
            safe_sleep()

            for off in ADDRESS_OFFSETS:
                try:
                    if kind in ("MW", "MD"):
                        addr = off + num
                        cnt = 2 if kind == "MD" else 1
                        r = try_read_holding(c, addr, cnt)
                        results.append((f"holding_off+{off}", addr, interpret_result(r)))
                    elif kind in ("MB", "MX"):
                        parent = (off + num) // 2
                        r = try_read_holding(c, parent, 1)
                        results.append((f"holding_parent_off+{off}", parent, interpret_result(r)))
                    elif kind == "IX":
                        addr = off + num
                        r = try_read_discrete(c, addr, 1)
                        results.append((f"discrete_off+{off}", addr, interpret_result(r)))
                except Exception as e:
                    results.append((f"error_off+{off}", off, f"EXC: {e}"))
                safe_sleep()

            if kind in ("MX", "MB", "MW"):
                r_coil = try_read_coils(c, num, 1)
                results.append(("coils_raw", num, interpret_result(r_coil)))
                safe_sleep()
                for off in ADDRESS_OFFSETS:
                    r_coil = try_read_coils(c, off + num, 1)
                    results.append((f"coils_off+{off}", off + num, interpret_result(r_coil)))
                    safe_sleep()

            print(" attempts:")
            for tname, a, val in results:
                print(f"  - {tname:25} addr={a:6} -> {val}")
            summary[label] = [val for _, _, val in results]

        print("\n-- offset sanity read for MW100 as 100 and 99 --")
        for idx in (100, 99):
            r = try_read_holding(c, idx, 1)
            print(f" read_holding({idx},1) -> {interpret_result(r)}")
            safe_sleep()

        try:
            c.close()
        except Exception:
            pass
        print(f"\nEnd tests for unit_id = {unit}\n")

        print("=== SUMMARY for unit_id", unit, "===")
        for label, vals in summary.items():
            print(f"{label}: {vals}")
        print("====================================")

        safe_sleep()

    print("\n=== DIAGNOSTIC TEST 2 COMPLETE ===\n")

if __name__ == "__main__":
    run_tests()
