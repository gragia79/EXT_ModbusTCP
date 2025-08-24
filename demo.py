# demo.py / demo.py
import time
import logging
from ext_modbus_blueprint import ModbusWrapper

logging.basicConfig(level=logging.INFO)

# --- LIVE PLC SETTINGS ---        # --- IMPOSTAZIONI PLC LIVE ---
PLC_IP = "192.168.1.22"             # Indirizzo IP del PLC
PLC_PORT = 502                      # Porta del PLC
PLC_UNIT_ID = 0  # Graziano confirmed  # ID unità Modbus (confermato da Graziano)

# --- Create wrapper with variables.txt ---     # --- Crea wrapper con variables.txt ---
mw = ModbusWrapper(ip=PLC_IP, port=PLC_PORT, variable_file="variables.txt")
mw.client.unit_id = PLC_UNIT_ID

print("=== STEP 1: Connect ===")     # === PASSO 1: Connessione ===
if not mw.alive():
    print(f"Could not connect to PLC {PLC_IP}:{PLC_PORT}")  # ⚠️ Impossibile connettersi al PLC ...
    exit(1)
print(f"Connected to {PLC_IP}:{PLC_PORT}, unit={PLC_UNIT_ID}\n")  # Connesso a ...

print("=== STEP 2: Loaded variables ===")     # === PASSO 2: Variabili caricate ===
for name, obj in mw.variables.items():
    t = obj.__class__.__name__
    ro = getattr(obj, "readonly", False)
    init = getattr(obj, "initial_value", None)
    print(f"{name} ({t}) @ {obj.address} readonly={ro} init={init}")
    # Stampa nome, tipo, indirizzo, se è sola lettura, e valore iniziale
print()

print("=== STEP 3: Read initial values ===")     # === PASSO 3: Leggi valori iniziali ===
for name in mw.variables:
    val = mw.read_var(name)
    if val is None:
        print(f" • {name} -> None (not readable via Modbus)")   # Non leggibile via Modbus
    else:
        print(f" • {name} = {val}")    # Mostra valore letto
time.sleep(0.2)
print()

print("=== STEP 4: Write test values ===")     # === PASSO 4: Scrittura valori di test ===
for i, name in enumerate(mw.variables):
    obj = mw.variables[name]

    # Skip read-only (%IX) and constants (:=)
    # Salta variabili di sola lettura (%IX) e con valore costante (:=)
    if getattr(obj, "readonly", False) or getattr(obj, "initial_value", None) is not None:
        print(f" - skipping {name} (read-only or := default)")  # Salto...
        continue

    # Example write: Flags alternate True/False, Words get 100+i*10
    # Esempio di scrittura: Flag alterna True/False, Word = 100+i*10
    test_value = bool(i % 2) if obj.__class__.__name__ == "Flag" else (100 + i * 10)

    ok = mw.write_var(name, test_value)
    print(f" -> write {name} = {test_value} success={ok}")  # Scrive e mostra se ha avuto successo
    time.sleep(0.1)  # breathing space / pausa breve

print("\n=== STEP 5: Read back after writes ===")    # === PASSO 5: Leggi dopo scrittura ===
for name in mw.variables:
    val = mw.read_var(name)
    print(f" • {name} = {val}")   # Mostra nuovo valore letto
print()

print("=== END OF DEMO ===")      # === FINE DEMO ===