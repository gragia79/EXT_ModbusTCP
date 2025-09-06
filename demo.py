# demo.py Main Demo.py 
import time
import logging
from threading import Thread
from ext_modbus_blueprint import ModbusWrapper

logging.basicConfig(level=logging.INFO, format="%(message)s")

# --- PLC SETTINGS ---   
# PLC_IP = "192.168.1.22"
# PLC_PORT = 502
# PLC_UNIT_ID = 0  # Graziano confirmed


# --- PLC SETTINGS (simulation or real) ---
PLC_IP = "127.0.0.1"    # or "192.168.1.22" for Graziano’s real PLC
PLC_PORT = 1502         # 502 for real PLC
PLC_UNIT_ID = 1         # 0 for real PLC

mw = ModbusWrapper(ip=PLC_IP, port=PLC_PORT, unit_id=PLC_UNIT_ID, variable_file="variables.txt")
# STEP 1: Auto-polling group
print("=== STEP 1: Auto-polling group ===")
mw.add_polling_group("main", ["Word2", "Flag_RitVcc"], interval_ms=1000, max_cycles=0)

# STEP 2: Finite polling group (manual start)
print("=== STEP 2: Finite polling group (must be started manually) ===")
pg = mw.add_polling_group("page", ["Enable", "Preset"], interval_ms=500, max_cycles=5)


def main():


    print("=== STEP 0: Try to connect ===")
    if not mw.connect(retries=3, retry_delay=1.0):
        print("Initial connect failed, continuing offline mode...")
    else:
        print("Connected successfully.")
   
    # STEP 2b: Show auto-expanded aliases
    print("=== STEP 2b: Auto-expansion check for Word2 ===")
    aliases = [name for name in mw.variables.keys() if name.startswith("Word2")]
    for alias in sorted(aliases):
        wrapper = mw.variables[alias]
        print(f"Alias: {alias:12s} → {wrapper.address} ({wrapper.__class__.__name__})")
        print( mw.read_var(alias))
    
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

    # STEP 6: Byte/Word sync test
    print("=== STEP 6: Byte/Word sync test ===")
    try:
        print("Writing Word2 = 0x1234 ...")
        mw.write_var("Word2", 0x1234, force=True)

        print("Byte6 (low byte of Word2) =", mw.read_var("Byte6"))
        print("Word2 =", hex(mw.read_var("Word2")))

        print("Now writing Byte6 = 0xAB ...")
        mw.write_var("Byte6", 0xAB, force=True)

        print("Word2 =", hex(mw.read_var("Word2")))
        print("Byte6 =", hex(mw.read_var("Byte6")))

        print("Now toggling Flag80 ...")
        mw.write_var("Flag80", True, force=True)

        print("Flag80 =", mw.read_var("Flag80"))
        print("Byte6 =", bin(mw.read_var("Byte6")))
        print("Word2 =", hex(mw.read_var("Word2")))
    except Exception as e:
        print("Byte/Word sync test failed:", e)

    # STEP 7: Integration idle loop (non-blocking)
    print("=== STEP 7: Integration-ready idle loop ===")
    print("Now the script keeps running (does NOT exit).")
    print("Press CTRL+C to quit manually.")


if __name__ == "__main__":


    try:
        while True:
            if not mw.alive():
                logging.debug("Main loop: PLC not connected, waiting...")
                # Optional: try reconnect automatically
                mw.connect(retries=1, retry_delay=2.0)
            else:
                main()
            time.sleep(2)
    except KeyboardInterrupt:
        print("Exiting demo...")

