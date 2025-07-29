from pyModbusTCP.client import ModbusClient
import time
import logging

class ModbusWrapper:
    def __init__(self, ip, port=502):
        self.client = ModbusClient(host=ip, port=port, auto_open=True)
        self.variables = {}  # Dictionary to store parsed variables
        self.last_alive = None
        logging.basicConfig(level=logging.INFO)

    def alive(self):
        """Checks if the connection is alive."""
        if self.client.is_open():
            self.last_alive = time.time()
            return True
        try:
            return self.client.open()
        except Exception as e:
            logging.error(f"[ALIVE ERROR] {e}")
            return False

    def read_var(self, name):
        """Placeholder to read a variable by name"""
        # Will expand after loading vars
        return self.variables.get(name)

    def write_var(self, name, value):
        """Placeholder to write a variable by name"""
        pass  # To be implemented with type checks

    def load_variables_from_file(self, filepath):
        """To be implemented: parse .txt or .csv file"""
        pass

    def polling_group(self, var_list, interval_ms):
        """Refresh vars every X ms (basic loop placeholder)"""
        while True:
            for var in var_list:
                self.read_var(var)
            time.sleep(interval_ms / 1000)

