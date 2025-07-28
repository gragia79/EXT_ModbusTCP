# 🧭 Project Workflow – ModbusTCP Python Wrapper

---

## ✅ Phase 1: Variable Handling  
### 🇬🇧 English  
- [ ] Analyze and define all variable types (IX, QX, MW, MB, MX, etc.)  
- [ ] Support BOOL, BYTE, WORD, DWORD  
- [ ] Auto-handle overlaps (e.g. MW0 → MB0/MB1/MX0-15)  

### 🇮🇹 Italiano  
- [ ] Analizzare e definire tutti i tipi di variabili (IX, QX, MW, MB, MX, ecc.)  
- [ ] Supportare BOOL, BYTE, WORD, DWORD  
- [ ] Gestione automatica delle sovrapposizioni (es. MW0 → MB0/MB1/MX0-15)  

---

## ✅ Phase 2: File Format  
### 🇬🇧 English  
- [ ] Propose `.txt` or `.csv` format for easy editing  
- [ ] Include headers: Name, Address, Type, Description  
- [ ] Confirm formatting rules with client  

### 🇮🇹 Italiano  
- [ ] Proporre formato `.txt` o `.csv` per una facile modifica  
- [ ] Includere intestazioni: Nome, Indirizzo, Tipo, Descrizione  
- [ ] Confermare le regole di formattazione con il cliente  

---

## ✅ Phase 3: API Structure  
### 🇬🇧 English  
- [ ] Access with `.flag("...")`, `.word("...")`  
- [ ] Use `.value` and `.isChanged()` logic  
- [ ] Optional: callbacks or manual update methods  

### 🇮🇹 Italiano  
- [ ] Accesso tramite `.flag("...")`, `.word("...")`  
- [ ] Utilizzare la logica `.value` e `.isChanged()`  
- [ ] Opzionale: callback o metodi di aggiornamento manuale  

---

## ✅ Phase 4: Polling System  
### 🇬🇧 English  
- [ ] Group-based polling (e.g. `.group1.refresh(500ms)`)  
- [ ] Multi-group support  
- [ ] Logging toggle (dev/production)  

### 🇮🇹 Italiano  
- [ ] Polling basato su gruppi (es. `.group1.refresh(500ms)`)  
- [ ] Supporto multi-gruppo  
- [ ] Attivazione/disattivazione log (sviluppo/produzione)  

---

## ✅ Phase 5: Multi-IP & Logging  
### 🇬🇧 English  
- [ ] Each class instance manages one IP  
- [ ] Logging system included (optional)  
- [ ] Auto-reset `.isChanged()` on read  

### 🇮🇹 Italiano  
- [ ] Ogni istanza della classe gestisce un IP  
- [ ] Sistema di logging incluso (opzionale)  
- [ ] Reset automatico di `.isChanged()` alla lettura  

---

📝 *Feel free to edit or comment on any section above.*  
✍️ *Sentiti libero di modificare o commentare qualsiasi sezione sopra.*
