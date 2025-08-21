# demo.py
from ext_modbus_blueprint import ModbusWrapper
import time
import logging

logging.basicConfig(level=logging.INFO)

# --- LIVE PLC SETTINGS ---
PLC_IP = "192.168.1.22"
PLC_PORT = 502
PLC_UNIT_ID = 0  # Graziano confirmed

# Create wrapper with Graziano's PLC details + variables file
mw = ModbusWrapper(ip=PLC_IP, port=PLC_PORT, variable_file="variables.txt")
mw.client.unit_id = PLC_UNIT_ID  # pyModbusTCP requires explicit unit_id

print("=== Loaded Variables from variables.txt ===")
for name, obj in mw.variables.items():
    t = obj.__class__.__name__
    init = getattr(obj, "initial_value", None)
    ro = getattr(obj, "readonly", False)
    print(f"{name} ({t}) @ {obj.address} -> init={init} readonly={ro} desc='{getattr(obj,'description', '')}'")

print("\n=== LIVE TEST MODE ===")

# --- STEP 1: Check connection ---
alive = mw.alive()
print(f"[alive()] Connection status: {alive}\n")
if not alive:
    print("⚠️ Could not connect to PLC. Check VPN / IP / port 502.")
    exit(1)

# --- STEP 2: Read initial values ---
print("Initial values (read from PLC):")
for name in mw.variables:
    val = mw.read_var(name)
    print(f" • {name} = {val}")
print()

# --- STEP 3: Try writing safe test values ---
print("Writing test values (skipping := defaults unless force=True):")
for i, name in enumerate(mw.variables):
    obj = mw.variables[name]

    # Skip read-only or := values unless forced
    if getattr(obj, "readonly", False):
        print(f" - skipping {name} (read-only)")
        continue
    if getattr(obj, "initial_value", None) is not None:
        print(f" - skipping {name} (initial := present)")
        continue

    # Write test values (Flags → alternating True/False, others → 10, 20, 30…)
    if obj.__class__.__name__ == "Flag":
        mw.write_var(name, bool(i % 2))
    else:
        mw.write_var(name, (i + 1) * 10)

# --- STEP 4: Read back after writes ---
print("Values after write (read back from PLC):")
for name in mw.variables:
    print(f" • {name} = {mw.read_var(name)}")
print()

# --- STEP 5: Demonstrate isChanged() ---
print("Checking isChanged() behaviour (first call True if changed, second False):")
for name, obj in mw.variables.items():
    if hasattr(obj, "isChanged"):
        print(f" {name} changed? {obj.isChanged()}")
        print(f" {name} changed now? {obj.isChanged()}")
print()

# --- STEP 6: Polling demo (first 2 variables) ---
poll_vars = list(mw.variables.keys())[:2]
print(f"Starting polling group for {poll_vars} (500 ms) — running 3 cycles...")
mw.add_polling_group("demo_group", poll_vars, interval_ms=500)
time.sleep(1.6)  # let it run ~3 cycles
mw.stop_polling_group("demo_group")

print("\n=== END OF LIVE DEMO ===")
