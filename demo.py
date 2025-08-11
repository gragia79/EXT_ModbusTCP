# demo.py
from ext_modbus_blueprint import ModbusWrapper
import time

# Create wrapper (dry-run, using variables.txt)
mw = ModbusWrapper(ip="127.0.0.1", variable_file="variables.txt")

print("=== Loaded Variables ===")
for name, obj in mw.variables.items():
    t = obj.__class__.__name__
    init = getattr(obj, "initial_value", None)
    ro = getattr(obj, "readonly", False)
    print(f"{name} ({t}) @ {obj.address} -> init={init} readonly={ro} desc='{getattr(obj,'description', '')}'")

print("\n=== DRY RUN PROTOTYPE ===")

alive = mw.alive()
print(f"[alive()] Connection status: {alive}\n")

print("Initial values:")
for name in mw.variables:
    print(f" • {name} = {mw.read_var(name)}")
print()

# Simulate writing new values (BUT skip variables with initial_value unless force=True)
print("Writing new values (skipping := defaults):")
for i, name in enumerate(mw.variables):
    obj = mw.variables[name]
    # skip if initial_value present (client wants to "learn once")
    if getattr(obj, "initial_value", None) is not None:
        print(f" - skipping {name} (initial := present)")
        continue
    if obj.__class__.__name__ == "Flag":
        mw.write_var(name, bool(i % 2))
    else:
        mw.write_var(name, (i + 1) * 10)

print("Values after write:")
for name in mw.variables:
    print(f" • {name} = {mw.read_var(name)}")
print()

# Check isChanged() behaviour
print("Checking isChanged() behaviour (first call True if changed, second call False):")
for name, obj in mw.variables.items():
    if hasattr(obj, "isChanged"):
        print(f" {name} changed? {obj.isChanged()}")
        print(f" {name} changed now? {obj.isChanged()}")
print()

# Start a polling group for first two variables (demo)
poll_vars = list(mw.variables.keys())[:2]
print(f"Starting polling group for {poll_vars} (500 ms) — running 3 cycles...")
mw.add_polling_group("demo_group", poll_vars, interval_ms=500)
time.sleep(1.6)  # let it run ~3 cycles
mw.stop_polling_group("demo_group")

print("\n=== END OF DEMO ===")
