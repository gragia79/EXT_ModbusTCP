# demo.py Main Demo.py 
import time
import logging
from threading import Thread
from ext_modbus_blueprint import ModbusWrapper

logging.basicConfig(level=logging.INFO, format="%(message)s")

# --- PLC SETTINGS ---   
PLC_IP = "192.168.1.22"
PLC_PORT = 502
PLC_UNIT_ID = 0  # Graziano confirmed


# # --- PLC SETTINGS (simulation or real) ---
# PLC_IP = "127.0.0.1"    # or "192.168.1.22" for Graziano’s real PLC
# PLC_PORT = 1502         # 502 for real PLC
# PLC_UNIT_ID = 1         # 0 for real PLC


# create wrapper (auto_expand_words default = False -> no mass expansion)
mw = ModbusWrapper(ip=PLC_IP, port=PLC_PORT, unit_id=PLC_UNIT_ID, variable_file="variables.txt")

# STEP 1: Auto-polling group
print("=== STEP 1: Auto-polling group ===")
mw.add_polling_group("main", ["Word2", "Flag_RitVcc"], interval_ms=1000, max_cycles=0)

# STEP 2: Finite polling group (manual start)
print("=== STEP 2: Finite polling group (must be started manually) ===")
pg = mw.add_polling_group("page", ["Enable", "Preset"], interval_ms=500, max_cycles=5)


def main():
    # STEP 0: Try to connect
    print("=== STEP 0: Try to connect ===")
    if not mw.connect(retries=3, retry_delay=1.0):
        print("Initial connect failed, continuing offline mode...")
    else:
        print("Connected successfully.")

    # STEP 2b: Explicit expansion for Word2 (only this word)
    print("=== STEP 2b: Explicit expansion for Word2 ===")
    created = mw.expansion("Word2")   # <-- this creates only aliases for Word2
    print("Created aliases:", created)

    # List the aliases we now have for Word2
    print("Listing Word2-related aliases in mw.variables:")
    aliases = [name for name in mw.variables.keys() if name.startswith("Word2_")]
    for alias in sorted(aliases):
        wrapper = mw.variables[alias]
        print(f"  {alias:20s} -> {wrapper.address} ({wrapper.__class__.__name__})")

    # STEP 3: Manual read
    print("=== STEP 3: Manual read test ===")
    try:
        print("Reading Word2 manually:", mw.read_var("Word2"))
    except Exception as e:
        print("Manual read failed:", e)

    # STEP 4: Manual write
    print("=== STEP 4: Manual write test ===")
    try:
        mw.write_var("Preset", 42, force=True)
        print("Preset written = 42")
    except Exception as e:
        print("Manual write failed:", e)

    # STEP 5: Start finite polling group
    print("=== STEP 5: Start finite polling group ===")
    pg.start()
    time.sleep(0.5)  # give it a moment to run a few cycles

    # STEP 6: Byte/Word/Bit sync test using explicit aliases
    print("=== STEP 6: Byte/Word/Bit sync test (using aliases) ===")
    try:
        print("Writing Word2_LowByte = 0xAB ...")
        mw.write_var("Word2_LowByte", 0xAB, force=True)
        print("After low-byte write: Word2 =", hex(mw.read_var("Word2") or 0))

        print("Writing Word2_HighByte = 0x12 ...")
        mw.write_var("Word2_HighByte", 0x12, force=True)
        print("After high-byte write: Word2 =", hex(mw.read_var("Word2") or 0))

        print("Setting Word2_LowBit3 = True ...")
        mw.write_var("Word2_LowBit3", True, force=True)
        print("After setting bit3: Word2 =", hex(mw.read_var("Word2") or 0))
        print("Read bit alias Word2_LowBit3 =", mw.read_var("Word2_LowBit3"))

        # If you still have original Byte/Flag names declared in variables.txt, show them too:
        try:
            print("Byte6 (if declared) =", mw.read_var("Byte6"))
        except Exception:
            pass
        try:
            print("Flag80 (if declared) =", mw.read_var("Flag80"))
        except Exception:
            pass

    except Exception as e:
        print("Byte/Word sync test failed:", e)

    # STEP 7: Integration idle loop (non-blocking)
    print("=== STEP 7: Integration-ready idle loop ===")
    print("Now the script keeps running (does NOT exit). Press CTRL+C to quit manually.")

if __name__ == "__main__":
    try:
        while True:
            if not mw.alive():
                logging.debug("Main loop: PLC not connected, waiting...")
                # Optional: try reconnect automatically (one attempt each loop)
                mw.connect(retries=1, retry_delay=2.0)
            else:
                main()
            time.sleep(2)
    except KeyboardInterrupt:
        print("Exiting demo...")
