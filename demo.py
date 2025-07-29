# demo.py

from ext_modbus_blueprint import ModbusWrapper
import time

mw = ModbusWrapper(ip="127.0.0.1")
mw.variables = {"Flag1": False, "Word1": 123, "Byte1": 0x5A}

print("=== DRY RUN PROTOTYPE ===\n")

alive = mw.alive()
print(f"[alive()] Connection status: {alive}\n")

print("Initial values:")
for name in mw.variables:
    print(f" • {name} = {mw.read_var(name)}")
print()

print("Writing new values…")
mw.write_var("Flag1", True)
mw.write_var("Word1", 999)
mw.write_var("Byte1", 0xFF)

print("Values after write:")
for name in mw.variables:
    print(f" • {name} = {mw.read_var(name)}")
print()

print("Simulating polling group ['Flag1','Word1'] with 500 ms interval:")
for _ in range(2):
    for name in ["Flag1", "Word1"]:
        val = mw.read_var(name)
        print(f"  [poll] {name} = {val}")
    time.sleep(0.5)

print("\n=== END OF DEMO ===")
