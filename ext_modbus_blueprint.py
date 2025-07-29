from pyModbusTCP.client import ModbusClient  # Modbus client from pyModbusTCP
# Client Modbus fornito dalla libreria pyModbusTCP

import time  # Time module for delays and timestamps
# Modulo time per gestire ritardi e timestamp

import logging  # Logging module for error reporting and info tracking
# Modulo logging per la gestione di errori e messaggi informativi


class ModbusWrapper:
    def __init__(self, ip, port=502):
        # Create a ModbusClient instance with auto_open enabled
        # Crea un'istanza di ModbusClient con apertura automatica
        self.client = ModbusClient(host=ip, port=port, auto_open=True)

        # Dictionary to store variable states for simulation
        # Dizionario per memorizzare lo stato delle variabili nella simulazione
        self.variables = {}

        # Timestamp of the last successful connection check
        # Timestamp dell'ultima verifica di connessione riuscita
        self.last_alive = None

        # Set basic logging level to INFO
        # Imposta il livello base di logging su INFO
        logging.basicConfig(level=logging.INFO)


    def alive(self):
        """Checks if the connection is alive"""
        # Verifica se la connessione è attiva

        # 'is_open' is a property that tells if the client is connected
        # 'is_open' è una proprietà che indica se il client è connesso
        if self.client.is_open:
            # Save timestamp of successful connection check
            # Salva il timestamp della verifica di connessione riuscita
            self.last_alive = time.time()
            return True

        try:
            # Attempt to reconnect using the .open() method
            # Prova a riconnettersi usando il metodo .open()
            success = self.client.open()
            if success:
                self.last_alive = time.time()
            return success
        except Exception as e:
            # Log error if connection fails
            # Registra un errore se la connessione fallisce
            logging.error(f"[ALIVE ERROR] {e}")
            return False


    def read_var(self, name):
        """Return current value of a test variable"""
        # Restituisce il valore corrente di una variabile di test
        return self.variables.get(name)


    def write_var(self, name, value):
        """Set a test variable (in real lib this queues a Modbus write)"""
        # Imposta una variabile di test (nella versione finale questo invierà un comando Modbus)
        if name in self.variables:
            self.variables[name] = value
            return True
        else:
            # Raise error if variable not defined
            # Solleva un errore se la variabile non è definita
            raise KeyError(f"Variable '{name}' not defined")


    def load_variables_from_file(self, filepath):
        """To be implemented: parse .txt or .csv file"""
        # Da implementare: analizza file .txt o .csv per caricare variabili
        pass


    def polling_group(self, var_list, interval_ms):
        """Refresh vars every X ms (basic loop placeholder)"""
        # Aggiorna variabili ogni X millisecondi (loop base di simulazione)
        while True:
            for var in var_list:
                # Simulate reading each variable
                # Simula la lettura di ciascuna variabile
                self.read_var(var)
            # Convert milliseconds to seconds
            # Converte millisecondi in secondi
            time.sleep(interval_ms / 1000)