# test_1.py
# Comprehensive quick Modbus test for Graziano PLC (read/write, coils, bytes, bits, MD)
import time
import traceback
from pyModbusTCP.client import ModbusClient

# ---- CONFIG ----
PLC_HOST = "192.168.1.22"
PLC_PORT = 502
UNIT_IDS_TO_TRY = [0, 1]           # try common unit IDs
SLEEP = 0.18                       # breathing space between ops (seconds)


# # ---- CONFIG ----
# PLC_HOST = "127.0.0.1"
# PLC_PORT = 1502
# UNIT_IDS_TO_TRY = [0, 1]           # try common unit IDs
# SLEEP = 0.18                       # breathing space between ops (seconds)

# Addresses we want to check (from variables.txt)
# note: these are the "MW/MB/MX/MD" indexes used by your blueprint convention.
TEST_ITEMS = {
    "DubbleWord (MD0)": ("MD", 0),
    "Word2 (MW2)": ("MW", 2),
    "Byte6 (MB6)": ("MB", 6),
    "Flag80 (MX8.0)": ("MX", 8, 0),
    "Registro (MW100)": ("MW", 100),
    "Preset (MW100 :=100) (check read-only behavior)": ("MW", 100),
    "TimCorrente (MW200 - TIME)": ("MW", 200),
}

# A few extra ad-hoc addresses to test offsets (0 vs 1 based)
OFFSET_TESTS = [100, 99]  # try MW100 as 100 and 99


# ---- HELPERS ----
def connect_client(unit_id):
    c = ModbusClient(host=PLC_HOST, port=PLC_PORT, unit_id=unit_id, auto_open=True, auto_close=False)
    # enable debug if available (gives more verbose socket info)
    try:
        c.debug = True
    except Exception:
        pass
    return c


def safe_sleep():
    time.sleep(SLEEP)


def read_holding(c, addr, count=1):
    try:
        r = c.read_holding_registers(addr, count)
        return r
    except Exception as e:
        return f"EXC: {e}"


def read_coils(c, addr, count=1):
    try:
        r = c.read_coils(addr, count)
        return r
    except Exception as e:
        return f"EXC: {e}"


def write_single_register(c, addr, value):
    try:
        r = c.write_single_register(addr, int(value))
        return r
    except Exception as e:
        return f"EXC: {e}"


def write_multiple_registers(c, addr, values):
    try:
        r = c.write_multiple_registers(addr, list(map(int, values)))
        return r
    except Exception as e:
        return f"EXC: {e}"


def write_single_coil(c, addr, value):
    try:
        r = c.write_single_coil(addr, bool(value))
        return r
    except Exception as e:
        return f"EXC: {e}"


def read_item(c, kind, num, bit=None):
    # replicate the logic used in your blueprint (parent index logic)
    if kind == "MW":
        return read_holding(c, num, 1)
    if kind == "MD":
        # read two words (lo, hi) as in blueprint: read_holding_registers(num,2)
        return read_holding(c, num, 2)
    if kind == "MB":
        # parent word index = MB_index // 2
        parent = num // 2
        regs = read_holding(c, parent, 1)
        if isinstance(regs, list) and regs:
            word_val = regs[0]
            if num % 2 == 0:
                return word_val & 0xFF
            else:
                return (word_val >> 8) & 0xFF
        return regs
    if kind == "MX":
        # parent same as MB: num //2, then select byte then bit
        parent = num // 2
        regs = read_holding(c, parent, 1)
        if isinstance(regs, list) and regs:
            word_val = regs[0]
            byte_val = (word_val >> ((num % 2) * 8)) & 0xFF
            return bool((byte_val >> bit) & 1)
        return regs
    return None


# ---- RUN TESTS ----
def run_all_tests():
    print("\n=== MODBUS QUICK CHECK START ===\n")
    print(f"Target PLC: {PLC_HOST}:{PLC_PORT}")
    print()

    for unit in UNIT_IDS_TO_TRY:
        print("=" * 60)
        print(f"Testing with unit_id = {unit}")
        print("- open client -")
        c = connect_client(unit)
        ok = False
        try:
            ok = c.open()
        except Exception as e:
            print("open() raised exception:", e)
        print("open() ->", ok)
        safe_sleep()

        # raw socket info from client if open
        try:
            sock = getattr(c, "_client_socket", None)
            if sock:
                print("Connected socket:", sock)
        except Exception:
            pass
        print()

        # 1) read a small range of holding registers (0..10) to see general availability
        print("-> Read holding registers 0..9 (quick health check)")
        regs = read_holding(c, 0, 10)
        print(" read_holding(0,10) ->", regs)
        safe_sleep()

        # 2) read coils 0..15
        print("\n-> Read coils 0..15 (in case flags are coils)")
        coils = read_coils(c, 0, 16)
        print(" read_coils(0,16) ->", coils)
        safe_sleep()

        # 3) test the named items from variables.txt with blueprint logic
        print("\n-> Test specific variables from variables.txt (using blueprint mapping logic):")
        for label, info in TEST_ITEMS.items():
            try:
                if info[0] == "MX":
                    kind, num, bit = info
                    res = read_item(c, kind, num, bit)
                else:
                    kind, num = info[:2]
                    res = read_item(c, kind, num)
            except Exception as e:
                res = f"EXC: {traceback.format_exc()}"
            print(f" {label:45} -> {res}")
            safe_sleep()

        # 4) test offset possibility (0-based vs 1-based)
        print("\n-> Offset test (MW100 as index 100 and 99):")
        for a in OFFSET_TESTS:
            r = read_holding(c, a, 1)
            print(f" read_holding({a},1) -> {r}")
            safe_sleep()

        # 5) try write tests (non-destructive first): small write on a test safe address
        # WARNING: if you have no safe test register, pick one known to be for testing.
        # We'll try MW100 as an example but will restore it afterwards if possible.
        print("\n-> WRITE tests (attempt write and read back).")
        test_reg = 100
        read_before = read_holding(c, test_reg, 1)
        print(f" read before MW{test_reg} -> {read_before}")
        safe_sleep()

        test_value = 4321
        print(f" try write_single_register({test_reg}, {test_value}) ->", end=" ")
        wr = write_single_register(c, test_reg, test_value)
        print(wr)
        safe_sleep()

        print(" read after write ->", read_holding(c, test_reg, 1))
        safe_sleep()

        # restore original if it's numeric and write succeeded
        if isinstance(read_before, list) and read_before and isinstance(read_before[0], int):
            orig = read_before[0]
            print(f" restoring original value {orig} into MW{test_reg} ->", end=" ")
            rr = write_single_register(c, test_reg, orig)
            print(rr)
            safe_sleep()
            print(" read after restore ->", read_holding(c, test_reg, 1))
            safe_sleep()
        else:
            print(" skipping restore (no numeric original value detected or read failed).")
            safe_sleep()

        # 6) Try bit/byte writes for MB/MX if the PLC treats them as holding register bytes
        print("\n-> Try bit write (MX) via read-modify-write like your blueprint:")
        # example: MX8.0 -> MB parent is 8//2 = 4 ; try toggling bit 0
        mx_num = 8
        bit = 0
        parent = mx_num // 2
        print(" read parent word before ->", read_holding(c, parent, 1))
        safe_sleep()
        # set bit by writing parent word (naive attempt)
        print(f" attempt to set bit {bit} in MX{mx_num}.0 by reading and re-writing parent {parent}")
        regs_parent = read_holding(c, parent, 1)
        if isinstance(regs_parent, list) and regs_parent:
            wordv = regs_parent[0]
            # compute byte and set bit
            byte_index = mx_num % 2
            if byte_index == 0:
                low = wordv & 0xFF
                new_low = low | (1 << bit)
                new_word = (wordv & 0xFF00) | new_low
            else:
                high = (wordv >> 8) & 0xFF
                new_high = high | (1 << bit)
                new_word = (wordv & 0x00FF) | (new_high << 8)
            print(f" write_single_register({parent}, {new_word}) ->", write_single_register(c, parent, new_word))
            safe_sleep()
            print(" read parent after ->", read_holding(c, parent, 1))
        else:
            print(" cannot perform MX write test because parent read failed.")
        safe_sleep()

        # 7) Try coil write (safe) on coil 0
        print("\n-> Try a coil write/read on coil 0 (in case flags are coils):")
        print(" write_single_coil(0,True) ->", write_single_coil(c, 0, True))
        safe_sleep()
        print(" read_coils(0,1) ->", read_coils(c, 0, 1))
        safe_sleep()
        print(" write_single_coil(0,False) ->", write_single_coil(c, 0, False))
        safe_sleep()
        print(" read_coils(0,1) ->", read_coils(c, 0, 1))
        safe_sleep()

        # 8) extra: MD / DWord test (read 2 regs)
        print("\n-> MD/32-bit read test at MD0 (read_holding(0,2)) ->", read_holding(c, 0, 2))
        safe_sleep()

        # done with this unit
        try:
            c.close()
        except Exception:
            pass
        print(f"\nEnd tests for unit_id = {unit}\n")
        safe_sleep()

    print("=" * 60)
    print("All tests complete. Paste the console output back here and I will interpret it.")
    print("\n=== MODBUS QUICK CHECK END ===\n")


if __name__ == "__main__":
    run_all_tests()

""" 
What to look for in the script output (how you’ll know what broke)

open() -> True means socket opened. If open() is False check network/VPN.

read_holding(0,10) should return a list of ints OR None/exception. If it returns a list, the PLC answers holding register reads. If it returns None or EXC, the PLC either didn't answer or the request was refused.

read_coils(0,16) helps detect whether flags are coils (discrete) instead of bits inside holding registers. If coils return useful booleans, maybe MX addresses are coils not bits in registers.

write_single_register(100,4321): if this returns True and the immediate read shows 4321, PLC accepted the write. If False/None or read unchanged, write was rejected.

For MX/MB tests: parent read/write operations will reveal whether your read-modify-write approach is valid.

Try unit_id 0 and 1 — if one works and the other fails, it's a unit-id mismatch.

When you paste the full console, I’ll point exactly to the failing step and what to change (unit id, offset, coil vs holding, permissions).
"""