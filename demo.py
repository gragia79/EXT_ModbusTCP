from ext_modbus_blueprint import ModbusWrapper  # Import custom Modbus wrapper class
# Importa la classe ModbusWrapper personalizzata

import time  # Used for sleep intervals in polling simulation
# Utilizzato per gli intervalli di attesa nella simulazione di polling

# Create instance of ModbusWrapper with loopback IP for testing
# Crea un'istanza di ModbusWrapper con indirizzo IP di loopback per il test
mw = ModbusWrapper(ip="127.0.0.1")

# Initialize test variables with sample values
# Inizializza variabili di test con valori di esempio
mw.variables = {
    "Flag1": False,     # Boolean flag variable / Variabile booleana
    "Word1": 123,       # Integer register / Registro intero
    "Byte1": 0x5A       # Hex byte value / Valore byte esadecimale
}

print("=== DRY RUN PROTOTYPE ===\n")  # Header for dry run output
# Intestazione per l'output della simulazione

# Check if Modbus connection is alive (simulated)
# Verifica se la connessione Modbus è attiva (simulata)
alive = mw.alive()
print(f"[alive()] Connection status: {alive}\n")  # Print connection status
# Stampa lo stato della connessione

# Show initial variable values
# Mostra i valori iniziali delle variabili
print("Initial values:")
for name in mw.variables:
    print(f" • {name} = {mw.read_var(name)}")  # Read and print variable
    # Leggi e stampa il valore della variabile
print()

# Simulate writing new values to existing variables
# Simula la scrittura di nuovi valori sulle variabili esistenti
print("Writing new values…")
mw.write_var("Flag1", True)    # Set boolean flag to True
# Imposta il flag booleano su True
mw.write_var("Word1", 999)     # Update integer register
# Aggiorna il registro intero
mw.write_var("Byte1", 0xFF)    # Set byte to hex FF
# Imposta il byte su esadecimale FF

# Display updated values after write operations
# Mostra i valori aggiornati dopo le operazioni di scrittura
print("Values after write:")
for name in mw.variables:
    print(f" • {name} = {mw.read_var(name)}")  # Print updated values
    # Stampa i valori aggiornati
print()

# Simulate polling for two variables at 500 ms interval
# Simula il polling di due variabili con intervallo di 500 ms
print("Simulating polling group ['Flag1','Word1'] with 500 ms interval:")
for _ in range(2):  # Loop twice to simulate periodic reads
    # Ciclo due volte per simulare letture periodiche
    for name in ["Flag1", "Word1"]:
        val = mw.read_var(name)  # Read each variable from the wrapper
        # Leggi ogni variabile dal wrapper
        print(f"  [poll] {name} = {val}")  # Print polled value
        # Stampa il valore ottenuto dal polling
    time.sleep(0.5)  # Wait 500 ms between polling cycles
    # Attendi 500 ms tra i cicli di polling

print("\n=== END OF DEMO ===")  # End of output marker
# Indicatore di fine output