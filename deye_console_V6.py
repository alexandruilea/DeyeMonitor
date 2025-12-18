import time
import asyncio
import threading
import customtkinter as ctk
from pysolarmanv5 import PySolarmanV5
from kasa import Discover

# --- HARDWARE CONFIG ---
DEYE_IP, DEYE_SN = "192.168.0.122", 3127036880
TAPO_IP = "192.168.0.158"
TAPO_USER, TAPO_PASS = "alexandruilea95@gmail.com", "env_password"

class TapoManager:
    def __init__(self):
        self.device, self.target_state, self.current_state = None, None, False
        self.is_connected = False
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main_task())

    async def _main_task(self):
        while True:
            try:
                if self.device is None:
                    self.device = await Discover.discover_single(TAPO_IP, username=TAPO_USER, password=TAPO_PASS)
                await self.device.update()
                self.current_state = self.device.is_on
                self.is_connected = True
                if self.target_state is not None:
                    if self.target_state != self.current_state:
                        if self.target_state: await self.device.turn_on()
                        else: await self.device.turn_off()
                    self.target_state = None 
            except:
                self.is_connected, self.device = False, None 
            await asyncio.sleep(2)

class DeyeApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Deye Inverter EMS Pro")
        self.geometry("650x1000")
        ctk.set_appearance_mode("dark")
        
        # Adjustable Parameters
        self.cfg_start_soc = ctk.StringVar(value="70")
        self.cfg_stop_soc = ctk.StringVar(value="32")
        self.cfg_headroom = ctk.StringVar(value="4000")
        self.cfg_phase_max = ctk.StringVar(value="7000")
        self.cfg_safety_lv = ctk.StringVar(value="185.0")
        self.cfg_hv_threshold = ctk.StringVar(value="252.0")
        self.cfg_lv_threshold = ctk.StringVar(value="210.0")
        self.cfg_lv_delay = ctk.StringVar(value="10")
        self.cfg_target_phase = ctk.StringVar(value="L1")
        self.cfg_export_active = ctk.BooleanVar(value=True)
        self.cfg_export_limit = ctk.StringVar(value="5000")
        self.cfg_manual_mode = ctk.BooleanVar(value=False)
        
        self.logic_widgets = [] # For red-out in manual mode
        self.lv_timer_start, self.modbus = None, None
        self.tapo = TapoManager() 

        self.setup_ui()
        threading.Thread(target=self.data_loop, daemon=True).start()

    def get_safe_val(self, var, default):
        try:
            val = var.get()
            return float(val) if "." in val else int(val)
        except: return default

    def setup_ui(self):
        self.grid_columnconfigure((0, 1, 2), weight=1)
        self.lbl_status = ctk.CTkLabel(self, text="CONNECTING...", font=("Roboto", 24, "bold"))
        self.lbl_status.grid(row=0, column=0, columnspan=3, pady=10)

        self.lbl_solar = ctk.CTkLabel(self, text="SOLAR\n0W", font=("Roboto", 22, "bold"), text_color="#FFD700")
        self.lbl_solar.grid(row=1, column=0)
        self.lbl_soc = ctk.CTkLabel(self, text="BATTERY\n0%", font=("Roboto", 22, "bold"))
        self.lbl_soc.grid(row=1, column=1)
        self.lbl_grid = ctk.CTkLabel(self, text="GRID\n0W", font=("Roboto", 22, "bold"))
        self.lbl_grid.grid(row=1, column=2)

        for i, name in enumerate(["L1", "L2", "L3"]):
            frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
            frame.grid(row=i+2, column=0, columnspan=3, padx=20, pady=5, sticky="ew")
            frame.grid_columnconfigure(1, weight=1)
            v = ctk.CTkLabel(frame, text="0.0 V", font=("Roboto", 22, "bold"), text_color="#00BFFF", width=110)
            v.grid(row=0, column=0, padx=10)
            bar = ctk.CTkProgressBar(frame, height=18); bar.grid(row=0, column=1, padx=10, sticky="ew")
            l = ctk.CTkLabel(frame, text="0 W", font=("Roboto", 20, "bold"), width=95); l.grid(row=0, column=2, padx=10)
            setattr(self, f"bar_{name.lower()}", bar); setattr(self, f"lbl_v_{name.lower()}", v); setattr(self, f"lbl_l_{name.lower()}", l)

        # Settings
        settings_frame = ctk.CTkFrame(self)
        settings_frame.grid(row=5, column=0, columnspan=3, padx=20, pady=10, sticky="nsew")
        settings_frame.grid_columnconfigure((0,1,2,3,4,5), weight=1, uniform="ems")
        ctk.CTkLabel(settings_frame, text="EMS CONFIGURATION", font=("Roboto", 14, "bold")).grid(row=0, column=0, columnspan=6, pady=10)
        
        man_switch = ctk.CTkSwitch(settings_frame, text="MANUAL OVERRIDE MODE", variable=self.cfg_manual_mode, 
                                   command=self.update_manual_visuals, progress_color="#E74C3C", font=("Roboto", 12, "bold"))
        man_switch.grid(row=1, column=0, columnspan=6, pady=(0,20))

        # SOC Parameters - Centered
        self.add_setting_v(settings_frame, "Start SOC %", self.cfg_start_soc, 2, 1, False)
        self.add_setting_v(settings_frame, "Stop SOC %", self.cfg_stop_soc, 2, 2, False)
        self.add_setting_v(settings_frame, "Headroom W", self.cfg_headroom, 2, 3, False)

        # Phase & Export
        ctk.CTkLabel(settings_frame, text="Monitor Phase:", font=("Roboto", 11, "bold")).grid(row=4, column=0, sticky="e", padx=2, pady=15)
        self.phase_sel = ctk.CTkSegmentedButton(settings_frame, values=["L1", "L2", "L3"], variable=self.cfg_target_phase, height=28)
        self.phase_sel.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=15)
        self.exp_switch = ctk.CTkSwitch(settings_frame, text="Export D", variable=self.cfg_export_active, font=("Roboto", 11, "bold"))
        self.exp_switch.grid(row=4, column=3, sticky="e", padx=5, pady=15)
        self.add_setting_h(settings_frame, "Min Export:", self.cfg_export_limit, 4, 4, False)

        # Voltage
        self.add_setting_h(settings_frame, "High V (ON):", self.cfg_hv_threshold, 5, 0, False)
        self.add_setting_h(settings_frame, "Low V (OFF):", self.cfg_lv_threshold, 5, 2, False)
        self.add_setting_h(settings_frame, "LV Delay (s):", self.cfg_lv_delay, 5, 4, False)

        # Safety
        ctk.CTkLabel(settings_frame, text="SAFETY:", font=("Roboto", 11, "bold"), text_color="#E74C3C").grid(row=6, column=0, sticky="e", pady=20)
        self.add_setting_h(settings_frame, "Max Phase W:", self.cfg_phase_max, 6, 1, True)
        self.add_setting_h(settings_frame, "Critical LV:", self.cfg_safety_lv, 6, 3, True)

        self.btn_toggle = ctk.CTkButton(self, text="HP: SYNCING", command=self.manual_toggle_click, font=("Roboto", 20, "bold"), height=70)
        self.btn_toggle.grid(row=7, column=0, columnspan=3, pady=10, padx=40, sticky="ew")
        self.lbl_logic = ctk.CTkLabel(self, text="Logic: Initializing", font=("Roboto", 13), text_color="gray")
        self.lbl_logic.grid(row=8, column=0, columnspan=3, pady=5)

    def add_setting_v(self, master, label, var, r, c, is_safety):
        lbl = ctk.CTkLabel(master, text=label, font=("Roboto", 11))
        lbl.grid(row=r, column=c, pady=(0,2))
        ent = ctk.CTkEntry(master, textvariable=var, width=85, justify="center")
        ent.grid(row=r+1, column=c, padx=5, pady=(0,15))
        if not is_safety: self.logic_widgets.append((lbl, ent))

    def add_setting_h(self, master, label, var, r, c, is_safety):
        lbl = ctk.CTkLabel(master, text=label, font=("Roboto", 11, "bold"))
        lbl.grid(row=r, column=c, sticky="e", padx=2)
        ent = ctk.CTkEntry(master, textvariable=var, width=75, justify="center")
        ent.grid(row=r, column=c+1, sticky="w", padx=2)
        if not is_safety: self.logic_widgets.append((lbl, ent))

    def update_manual_visuals(self):
        is_man = self.cfg_manual_mode.get()
        color, state = ("#E74C3C", "disabled") if is_man else ("white", "normal")
        for lbl, ent in self.logic_widgets: 
            ent.configure(text_color=color, state=state)
            lbl.configure(text_color=color)
        self.phase_sel.configure(state=state); self.exp_switch.configure(state=state)

    def manual_toggle_click(self):
        if self.tapo.is_connected: self.tapo.target_state = not self.tapo.current_state

    def data_loop(self):
        while True:
            try:
                if self.modbus is None: self.modbus = PySolarmanV5(DEYE_IP, DEYE_SN, port=8899, auto_reconnect=True)
                raw = self.modbus.read_holding_registers(register_addr=588, quantity=90)
                d = {"soc": raw[0], "batt": raw[2] if raw[2]<32768 else raw[2]-65536, "pv": raw[84]+raw[85],
                     "grid": raw[37] if raw[37]<32768 else raw[37]-65536, "v": [raw[56]/10, raw[57]/10, raw[58]/10],
                     "w": [raw[62], raw[63], raw[64]]}
                self.after(0, self.update_dashboard, d)
                self.process_logic(d)
            except: self.modbus = None
            time.sleep(1.2)

    def update_dashboard(self, d):
        self.lbl_status.configure(text="SYSTEM ONLINE", text_color="#2ECC71")
        self.lbl_soc.configure(text=f"BATTERY\n{d['soc']}% ({d['batt']}W)")
        self.lbl_solar.configure(text=f"SOLAR\n{d['pv']}W")
        g_p = "+" if d['grid'] >= 0 else ""
        self.lbl_grid.configure(text=f"GRID\n{g_p}{d['grid']}W", text_color="#2ECC71" if d['grid'] < 0 else "#AAAAAA")
        lim = self.get_safe_val(self.cfg_phase_max, 7000)
        for i, p in enumerate(['l1', 'l2', 'l3']):
            getattr(self, f"bar_{p}").set(min(d['w'][i] / lim, 1.0))
            getattr(self, f"lbl_v_{p}").configure(text=f"{d['v'][i]} V")
            getattr(self, f"lbl_l_{p}").configure(text=f"{d['w'][i]} W")
        if not self.tapo.is_connected: self.btn_toggle.configure(text="HP: TAPO OFFLINE", fg_color="#3B3B3B")
        elif self.tapo.current_state: self.btn_toggle.configure(text="HEAT PUMP: RUNNING", fg_color="#27AE60")
        else: self.btn_toggle.configure(text="HEAT PUMP: STANDBY", fg_color="#C0392B")

    def process_logic(self, d):
        if not self.tapo.is_connected: return
        cur = self.tapo.current_state
        p_lim = self.get_safe_val(self.cfg_phase_max, 7000)
        v_crit = self.get_safe_val(self.cfg_safety_lv, 185.0)

        # 1. HARD SAFETY
        if cur:
            if any(w > p_lim for w in d['w']):
                self.logic_msg("SAFETY KILL: OVERLOAD", "#E74C3C"); self.tapo.target_state = False; return
            if any(v < v_crit for v in d['v']):
                self.logic_msg(f"SAFETY KILL: <{v_crit}V", "#E74C3C"); self.tapo.target_state = False; return

        if self.cfg_manual_mode.get():
            self.logic_msg("MANUAL MODE ACTIVE", "#E74C3C"); return

        # 2. VALIDATION LAYER (Flapping Protection)
        start_s, stop_s = self.get_safe_val(self.cfg_start_soc, 70), self.get_safe_val(self.cfg_stop_soc, 32)
        v_high, v_low = self.get_safe_val(self.cfg_hv_threshold, 252.0), self.get_safe_val(self.cfg_lv_threshold, 210.0)
        
        if start_s <= stop_s:
            self.logic_msg("ERR: START SOC must be > STOP SOC", "#A569BD"); self.mark_invalid(True); return
        if v_high <= v_low:
            self.logic_msg("ERR: HIGH V must be > LOW V", "#A569BD"); self.mark_invalid(True); return
        if v_low <= v_crit:
            self.logic_msg("ERR: LOW V must be > CRITICAL V", "#A569BD"); self.mark_invalid(True); return
        
        self.mark_invalid(False) # Clear error visuals if all OK

        # 3. AUTO LOGIC
        h_req, v_delay = self.get_safe_val(self.cfg_headroom, 4000), self.get_safe_val(self.cfg_lv_delay, 10)
        target_idx = ["L1", "L2", "L3"].index(self.cfg_target_phase.get())
        v_target, exp_w = d['v'][target_idx], (abs(d['grid']) if d['grid'] < 0 else 0)

        if cur:
            if v_target < v_low:
                if self.lv_timer_start is None: self.lv_timer_start = time.time()
                if (time.time() - self.lv_timer_start) >= v_delay:
                    self.logic_msg("OFF: UNDER-VOLTAGE TIMER", "red"); self.tapo.target_state = False
            elif d['soc'] <= stop_s:
                self.logic_msg("OFF: BATTERY LOW", "gray"); self.tapo.target_state = False
            else:
                self.lv_timer_start = None; self.logic_msg("Logic: Running - All OK", "#2ECC71")
        else:
            if v_target >= v_high:
                self.logic_msg(f"ON: HV DUMP ({v_target}V)", "cyan"); self.tapo.target_state = True
            elif self.cfg_export_active.get() and exp_w >= self.get_safe_val(self.cfg_export_limit, 5000):
                if all((p_lim - w) >= h_req for w in d['w']):
                    self.logic_msg(f"ON: EXPORT DUMP ({exp_w}W)", "gold"); self.tapo.target_state = True
            elif d['soc'] >= start_s:
                if all((p_lim - w) >= h_req for w in d['w']):
                    self.logic_msg("ON: AUTO-START (SOC)", "#2ECC71"); self.tapo.target_state = True
                else: self.logic_msg("Wait: Headroom insufficient", "orange")
            else: self.logic_msg("Wait: SOC Charging", "gray")

    def logic_msg(self, msg, color):
        self.after(0, lambda: self.lbl_logic.configure(text=msg, text_color=color))

    def mark_invalid(self, invalid):
        color = "#A569BD" if invalid else "white" # Purple for invalid
        for _, ent in self.logic_widgets: ent.configure(text_color=color)

if __name__ == "__main__":
    app = DeyeApp(); app.mainloop()