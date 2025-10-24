## Descrizione

Wrapper Python minimale per **Modbus TCP** che si connette a un PLC, carica `variables.txt` in oggetti wrapper (Word / Byte / Flag / DWord / Timer), genera automaticamente alias (Word → Byte → Bit), fornisce operazioni di lettura/scrittura e gestisce gruppi di polling in background (thread).

---

## Avvio rapido

```python
from ext_modbus_blueprint import ModbusWrapper

mw = ModbusWrapper(ip="192.168.1.22", port=502, unit_id=0, variable_file="variables.txt")
mw.connect(retries=3, retry_delay=1.0)
mw.add_polling_group("main", ["Word2","Flag_RitVcc"], interval_ms=1000, max_cycles=0)
print(mw.read_var("Word2"))
mw.write_var("Preset", 42, force=True)
```

---

## Funzionalità principali

* Parsifica `variables.txt` e crea wrapper per ogni variabile.
* Espansione automatica alias: **WORD → Low/High BYTE → BIT**.
* API di lettura/scrittura; usare `<code>force=True</code>` per ignorare `readonly`.
* `<code>alive()</code>` per check non bloccante dello stato PLC.
* Polling groups: thread daemon separati, `interval_ms` configurabile; `max_cycles=0` = ciclo infinito.
* Retry di lettura robusti e logging quando il PLC è offline.

---

## Wrapper (sintesi)

* **Flag** — singolo bit (BOOL / MX / IX), supporta `isChanged()`.
* **Byte** — valore 8-bit sincronizzato con Word e bit.
* **Word** — registro 16-bit, espanso in due byte + 16 bit.
* **DWord** — 32-bit (due Word), supporta endianness.
* **TimerWrapper** — struttura timer con `value`, `flag`, `isChanged()`.

*Tutti i wrapper rilevano cambiamenti e mantengono la sincronizzazione Word ↔ Byte ↔ Bit.*

---

## Polling — comportamento

* Creazione:

  ```python
  mw.add_polling_group(name, var_list, interval_ms, max_cycles)
  ```
* Ogni ciclo: `alive()` → `_read_with_retries` per ciascuna variabile → aggiornamento wrapper.
* Consigli: gruppi infiniti per monitoraggio continuo; gruppi finiti (max_cycles>0) per test o operazioni temporanee.

---

## Alias e sincronizzazione

Dichiarando ad es. `Word2 AT %MW2: WORD` vengono creati automaticamente:

* `Word2_LowByte`, `Word2_HighByte`
* `Word2_LowBit0..7`, `Word2_HighBit0..7`

Scrivere su **qualunque alias** aggiorna il parent e tutti gli alias dipendenti (byte → word → bit e viceversa).

---

## Funzioni importanti da personalizzare

* `parse_address(addr)` — parsing degli indirizzi.
* `parse_variables_file(filepath)` — regole variabili e readonly.
* `instantiate_wrappers(parsed)` — creazione wrapper e naming alias.
* `read_from_plc / write_to_plc` — accesso Modbus a basso livello (offset/base).
* `_sync_mw_to_mb_mx` — logica di sincronizzazione alias.
* `connect(retries, retry_delay)` — politica di riconnessione.

---

## demo.py

Script di esempio con modalità simulazione vs PLC reale, esempi di polling, lettura/scrittura manuale e test di sincronizzazione. **Testare prima su un simulatore PLC** prima di collegarsi a hardware reale.

---

## Best practice e avvertenze

* Mantieni la logica Modbus I/O in `ext_modbus_blueprint.py` (non nei wrapper).
* Fai backup prima di modificare il file principale; esegui `demo.py` dopo le modifiche.
* Le variabili `IX` sono auto-readonly: usa gli alias generati per accedere a byte/bit.
* Per forzare una scrittura su variabile protetta usare `<code>force=True</code>` con cautela.

---

## Nota rapida (evidenziata)

<span style="color:#b31d1d"><strong>Attenzione:</strong></span> provare sempre le modifiche su simulatore; modifiche dirette su PLC in produzione possono causare comportamenti imprevisti.

---
