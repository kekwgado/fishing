"""
================================================================================
Pesca Automática Inteligente — Minigame Circular (GTA RP / FiveM)
================================================================================
Funcionalidades:
  1. Detecção automática do início da pesca quando o círculo aparece na tela
     (referência: 'WhatsApp Image 2026-10-16 at 22.03.43.jpeg').
  2. Macro cadenciado inteligente com controle de malha fechada (PID adaptativo):
     monitora o raio do círculo interno mais claro e ajusta dinamicamente a
     velocidade/duração dos toques para manter o anel o mais estável possível.
  3. Detecção automática de conclusão do minigame com sucesso
     (referência: 'WhatsApp Image 2026-10-16 at 22.10.27.jpeg').
  4. Pressão automática da tecla 'E' para guardar o peixe no inventário.
  5. Opcional: auto-recast (arremessa a vara novamente após guardar).
  6. Janela de preview (HUD) com telemetria ao vivo.

Teclas de Controle:
  - F6 : Iniciar / Pausar macro
  - F7 : Armar / Desarmar detecção automática
  - ESC: Encerrar o script com segurança

Dependências:
  pip install opencv-python mss numpy keyboard pydirectinput
================================================================================
"""

import json
import os
import sys
import threading
import time
from collections import deque

import cv2
import numpy as np

# Diretório base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
TELEMETRY_DIR = os.path.join(BASE_DIR, "telemetria")

from pesca_config import (
    CONFIG_FILE,
    DEFAULT_CONFIG,
    GuardarDetector,
    detect_screen_resolution,
    load_and_sync_config,
)

def load_config():
    return load_and_sync_config()


# ----------------------------------------------------------------------------
# INPUT BACKEND (DirectInput para GTA V / FiveM ou Keyboard)
# ----------------------------------------------------------------------------
class InputManager:
    def __init__(self, backend="pydirectinput", reel_key="enter", catch_key="e", catch_hold=0.100):
        self.backend_name = backend
        self.reel_key = reel_key
        self.catch_key = catch_key
        self.catch_hold = catch_hold
        self.pydirectinput = None
        self.keyboard = None

        if backend == "pydirectinput":
            try:
                import pydirectinput
                pydirectinput.PAUSE = 0
                self.pydirectinput = pydirectinput
                print("[INPUT] Usando backend 'pydirectinput' (DirectX Scancodes).")
            except ImportError:
                print("[AVISO] 'pydirectinput' não encontrado. Recorrendo a 'keyboard'.")
                self.backend_name = "keyboard"

        if self.backend_name == "keyboard":
            try:
                import keyboard
                self.keyboard = keyboard
                print("[INPUT] Usando backend 'keyboard'.")
            except ImportError:
                print("[AVISO] 'keyboard' não instalado. Modo simulação sem teclas.")

    def press_reel(self):
        try:
            if self.pydirectinput:
                self.pydirectinput.keyDown(self.reel_key)
            elif self.keyboard:
                self.keyboard.press(self.reel_key)
        except Exception as e:
            print(f"[INPUT ERRO] press_reel: {e}")

    def release_reel(self):
        try:
            if self.pydirectinput:
                self.pydirectinput.keyUp(self.reel_key)
            elif self.keyboard:
                self.keyboard.release(self.reel_key)
        except Exception as e:
            print(f"[INPUT ERRO] release_reel: {e}")

    def trigger_catch(self):
        """Pressiona 'E' para guardar o peixe (ou recast) com hold de segurança."""
        try:
            if self.pydirectinput:
                self.pydirectinput.keyDown(self.catch_key)
                time.sleep(self.catch_hold)
                self.pydirectinput.keyUp(self.catch_key)
            elif self.keyboard:
                self.keyboard.press(self.catch_key)
                time.sleep(self.catch_hold)
                self.keyboard.release(self.catch_key)
            else:
                print(f"[MOCK INPUT] Pressionou tecla '{self.catch_key}'")
        except Exception as e:
            print(f"[INPUT ERRO] trigger_catch: {e}")
        finally:
            self.force_release_all()

    def force_release_all(self):
        try:
            if self.pydirectinput:
                self.pydirectinput.keyUp(self.reel_key)
                self.pydirectinput.keyUp(self.catch_key)
            elif self.keyboard:
                self.keyboard.release(self.reel_key)
                self.keyboard.release(self.catch_key)
        except Exception:
            pass


# ----------------------------------------------------------------------------
# TAPPER ADAPTATIVO (Thread independente de toques de alta precisão)
# ----------------------------------------------------------------------------
class AdaptiveTapper(threading.Thread):
    """Executa toques na tecla de pesca ('enter') com duração e intervalos ajustáveis dinamicamente."""

    def __init__(self, input_mgr, base_hold=0.108, base_rest=0.145):
        super().__init__(daemon=True)
        self.input_mgr = input_mgr
        self.hold = base_hold
        self.rest = base_rest
        self.active = threading.Event()
        self.quit = threading.Event()
        self.emergency_brake = threading.Event()
        self.is_down = False
        self.taps = 0
        self._lock = threading.Lock()

    def update_cadence(self, hold, rest, brake=False):
        with self._lock:
            self.hold = hold
            self.rest = rest
            if brake:
                self.emergency_brake.set()
            else:
                self.emergency_brake.clear()

    def start_taps(self):
        self.taps = 0
        self.emergency_brake.clear()
        self.active.set()

    def stop_taps(self):
        self.active.clear()
        self.emergency_brake.clear()
        self.input_mgr.release_reel()
        self.is_down = False

    def _wait(self, dur):
        end = time.perf_counter() + dur
        while time.perf_counter() < end and self.active.is_set() and not self.quit.is_set():
            rem = end - time.perf_counter()
            if rem > 0.005:
                time.sleep(0.001)

    def run(self):
        while not self.quit.is_set():
            if not self.active.is_set() or self.emergency_brake.is_set():
                if self.is_down:
                    self.input_mgr.release_reel()
                    self.is_down = False
                time.sleep(0.003)
                continue

            with self._lock:
                h = self.hold
                r = self.rest

            try:
                self.input_mgr.press_reel()
                self.is_down = True
                self.taps += 1
                self._wait(h)
            finally:
                self.input_mgr.release_reel()
                self.is_down = False

            if self.active.is_set() and not self.quit.is_set() and not self.emergency_brake.is_set():
                self._wait(r)


# ----------------------------------------------------------------------------
# VISÃO COMPUTACIONAL — ANALISADOR DO DISCO E ANEL
# ----------------------------------------------------------------------------
class CircleAnalyzer:
    """Segmentação e extração de métricas do minigame circular de pesca."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.screen_cfg = cfg["screen"]
        self.det_cfg = cfg["detection"]

        self.disc_region = self.screen_cfg["disc_region"]
        self.disc_cx = self.screen_cfg["disc_cx"]
        self.disc_cy = self.screen_cfg["disc_cy"]
        self.disc_r = float(self.screen_cfg["disc_r"])

        # Cache de mapas polares
        self._maps_cache = {}

    def update_geometry(self, region, cx, cy, r):
        self.disc_region = region
        self.disc_cx = cx
        self.disc_cy = cy
        self.disc_r = float(r)
        self._maps_cache.clear()

    def _get_polar_maps(self, h, w):
        key = (h, w, self.disc_cx, self.disc_cy, self.disc_r)
        if key not in self._maps_cache:
            cx = self.disc_cx - self.disc_region["left"]
            cy = self.disc_cy - self.disc_region["top"]
            yy, xx = np.mgrid[:h, :w]
            d = np.hypot(xx - cx, yy - cy).astype(np.float32)
            ang = ((np.degrees(np.arctan2(yy - cy, xx - cx)) + 360.0) % 360.0).astype(np.float32)

            r = self.disc_r
            # Coroa escura da borda do disco (escala proporcional ao raio)
            r_outer = r - max(3.0, r * 0.08)
            r_inner = r - max(10.0, r * 0.36)
            rim_m = (d >= r_inner) & (d <= r_outer)

            # Zona do anel interno de tensão
            inner_m = (d > max(6.0, r * 0.16)) & (d <= r - 2)
            # Núcleo central onde surge o check verde
            core_m = d < (r * 0.45)
            # Arco verde de progresso externo
            arc_m = (d > r + 2) & (d < r + max(12.0, r * 0.28))

            self._maps_cache[key] = (d, ang, rim_m, inner_m, core_m, arc_m, cx, cy)
        return self._maps_cache[key]

    def analyze(self, img_bgr):
        """Processa o frame do disco e extrai presença, raio do anel e check de vitória."""
        h, w = img_bgr.shape[:2]
        d, ang, rim_m, inner_m, core_m, arc_m, cx, cy = self._get_polar_maps(h, w)

        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        H, S, V = cv2.split(hsv)

        # 1. Borda escura do disco
        rim_dark_frac = float((V[rim_m] < self.det_cfg["disc_dark_v"]).mean())

        # 2. Anel interno claro (tensão do minigame)
        # Adaptado para funcionar tanto de dia quanto de noite ou com reflexo d'água
        v_min = self.det_cfg["ring_v_min"]
        s_min, s_max = self.det_cfg["ring_s_min"], self.det_cfg["ring_s_max"]
        h_max, h_min2 = self.det_cfg["ring_h_max"], self.det_cfg["ring_h_min2"]

        ring_mask = (
            inner_m
            & (V >= v_min)
            & (S >= s_min)
            & (S <= s_max)
            & ((H <= h_max) | (H >= h_min2))
        )
        n_ring = int(ring_mask.sum())
        ring_r = float(np.median(d[ring_mask])) if n_ring >= self.det_cfg["ring_min_px"] else None

        # 3. Arco verde externo de progresso
        green_mask = (H >= 35) & (H <= 90) & (S >= 40) & (V >= 80)
        arc = arc_m & green_mask
        arc_deg = 0
        if arc.any():
            arc_deg = len(np.unique((ang[arc] // 5).astype(np.int32) % 72)) * 5

        # 4. Checkmark de sucesso e peixe pego (WhatsApp Image 2026-10-16 at 22.10.27.jpeg)
        check_px = int((core_m & green_mask).sum())
        is_caught = check_px >= self.det_cfg["check_min_px"]

        # 5. Presença geral do disco na tela (WhatsApp Image 2026-10-16 at 22.03.43.jpeg)
        is_present = rim_dark_frac >= self.det_cfg["disc_rim_dark_frac"] and (
            n_ring >= self.det_cfg["ring_min_px"] or arc_deg >= 15 or is_caught
        )

        return {
            "present": is_present,
            "rim_dark": rim_dark_frac,
            "ring_r": ring_r,
            "n_ring": n_ring,
            "arc_deg": arc_deg,
            "check_px": check_px,
            "is_caught": is_caught,
            "cx": cx,
            "cy": cy,
        }


# ----------------------------------------------------------------------------
# CONTROLADOR DINÂMICO DE CADÊNCIA (PID adaptativo para estabilizar o anel)
# ----------------------------------------------------------------------------
class CadenceController:
    """Calcula a modulação dos toques para manter o anel interno no raio desejado."""

    def __init__(self, cfg):
        cad = cfg["cadence"]
        self.base_hold = cad["base_hold"]
        self.base_rest = cad["base_rest"]
        self.min_hold = cad["min_hold"]
        self.max_hold = cad["max_hold"]
        self.min_rest = cad["min_rest"]
        self.max_rest = cad["max_rest"]

        self.disc_r = float(cfg["screen"]["disc_r"])
        self.target_r = self.disc_r * cad["target_ratio"]
        self.kp_rest = cad["kp_rest"]
        self.kd_rest = cad["kd_rest"]
        self.kp_hold = cad["kp_hold"]
        self.invert = cad["invert_tension"]

        self.last_error = 0.0
        self.last_time = None
        self.ring_r_history = deque(maxlen=5)

    def reset(self):
        self.last_error = 0.0
        self.last_time = None
        self.ring_r_history.clear()

    def update(self, ring_r, t_now):
        """Retorna (hold_time, rest_time, emergency_brake, erro)."""
        if ring_r is None:
            # Sem leitura clara neste frame: mantém cadência base segura
            return self.base_hold, self.base_rest, False, 0.0

        self.ring_r_history.append(ring_r)
        # Filtro de mediana dos últimos frames para eliminar ruído de detecção
        r_filtered = float(np.median(self.ring_r_history))

        # Erro em relação ao alvo:
        # Se anel > alvo => erro > 0. Pressionar mais faz anel crescer.
        # Portanto, erro > 0 exige AUMENTAR o tempo de descanso (desacelerar toques)
        error = r_filtered - self.target_r
        if self.invert:
            error = -error

        dt = 0.016
        if self.last_time is not None and t_now > self.last_time:
            dt = max(0.001, t_now - self.last_time)
        d_error = (error - self.last_error) / dt
        self.last_error = error
        self.last_time = t_now

        # Modulação PID do descanso (rest)
        delta_rest = (self.kp_rest * error) + (self.kd_rest * d_error)
        rest = np.clip(self.base_rest + delta_rest, self.min_rest, self.max_rest)

        # Leve modulação do tempo pressionado (hold)
        delta_hold = self.kp_hold * error
        hold = np.clip(self.base_hold - delta_hold, self.min_hold, self.max_hold)

        # Freio de emergência se o anel estiver perigosamente próximo da borda
        emergency_brake = r_filtered >= (self.disc_r * 0.88)

        # Aceleração de emergência se estiver encolhendo perigosamente
        if r_filtered <= (self.disc_r * 0.22):
            rest = self.min_rest

        return float(hold), float(rest), bool(emergency_brake), float(error)


# ----------------------------------------------------------------------------
# BOT PRINCIPAL (Máquina de Estados)
# ----------------------------------------------------------------------------
class FishingBot:
    def __init__(self, cfg, input_mgr, tapper, analyzer, guardar_detector=None):
        self.cfg = cfg
        self.input_mgr = input_mgr
        self.tapper = tapper
        self.analyzer = analyzer
        self.guardar_detector = guardar_detector
        self.cadence_ctrl = CadenceController(cfg)

        self.state = "IDLE"
        self.armed = True
        self.stable_disc_frames = 0
        self.stable_check_frames = 0

        self.t_state = time.perf_counter()
        self.t_reel_start = 0.0
        self.gone_since = None

        self.current_info = None
        self.current_hold = cfg["cadence"]["base_hold"]
        self.current_rest = cfg["cadence"]["base_rest"]
        self.current_error = 0.0

        # Estatísticas da captura
        self.session_catches = 0
        self.reel_history = []

    def set_armed(self, armed):
        self.armed = armed
        print(f"[BOT] Armado = {'SIM' if self.armed else 'NÃO'}")
        if not self.armed and self.state in ("REELING", "WAIT_GUARDAR"):
            self._transition_to("IDLE")

    def _transition_to(self, new_state):
        old_state = self.state
        self.state = new_state
        self.t_state = time.perf_counter()

        if new_state == "IDLE":
            self.tapper.stop_taps()
            self.cadence_ctrl.reset()
            self.stable_disc_frames = 0
            self.stable_check_frames = 0
            self.gone_since = None

        elif new_state == "REELING":
            self.t_reel_start = self.t_state
            self.reel_history.clear()
            self.cadence_ctrl.reset()
            self.tapper.start_taps()
            print("[BOT] >>> FISGADA! Minigame iniciado. Puxando peixe com cadência inteligente...")

        elif new_state == "CAUGHT":
            self.tapper.stop_taps()
            self.session_catches += 1
            dur = self.t_state - self.t_reel_start
            print(f"[BOT] >>> SUCESSO! Minigame concluído em {dur:.1f}s com {self.tapper.taps} toques!")
            print("[BOT] >>> Aguardando o prompt '[E] Guardar Peixe' surgir na tela...")
            self._transition_to("WAIT_GUARDAR")

        elif new_state == "WAIT_GUARDAR":
            self.tapper.stop_taps()
            self.gone_since = None

        elif new_state == "COOLDOWN":
            self.tapper.stop_taps()
            self.gone_since = None

    def step(self, frame_bgr, t_now, guardar_bgr=None):
        info = self.analyzer.analyze(frame_bgr)
        self.current_info = info

        if not self.armed:
            if self.state != "IDLE":
                self._transition_to("IDLE")
            return

        # ------------------- ESTADO: IDLE -------------------
        if self.state == "IDLE":
            # Detecta surgimento do disco (WhatsApp Image 2026-10-16 at 22.03.43.jpeg)
            if info["present"] and not info["is_caught"]:
                self.stable_disc_frames += 1
                if self.stable_disc_frames >= self.cfg["detection"]["disc_stable_frames"]:
                    self._transition_to("REELING")
            else:
                self.stable_disc_frames = 0

        # ------------------- ESTADO: REELING -------------------
        elif self.state == "REELING":
            # 1. Verifica sucesso / checkmark (WhatsApp Image 2026-10-16 at 22.10.27.jpeg)
            if info["is_caught"]:
                self.stable_check_frames += 1
                if self.stable_check_frames >= self.cfg["detection"]["check_stable_frames"]:
                    self._transition_to("CAUGHT")
                    return
            else:
                self.stable_check_frames = 0

            # 2. Verifica perda do minigame (disco sumiu)
            if not info["present"]:
                if self.gone_since is None:
                    self.gone_since = t_now
                elif t_now - self.gone_since >= self.cfg["safety"]["reel_gone_s"]:
                    print("[BOT] Minigame encerrado (disco sumiu da tela).")
                    self._transition_to("COOLDOWN")
                    return
            else:
                self.gone_since = None

            # 3. Timeout de segurança
            if t_now - self.t_reel_start > self.cfg["safety"]["max_reel_s"]:
                print("[BOT] Tempo limite de recolhimento atingido. Abortando.")
                self._transition_to("COOLDOWN")
                return

            # 4. Controle dinâmico inteligente de cadência
            hold, rest, brake, err = self.cadence_ctrl.update(info["ring_r"], t_now)
            self.current_hold = hold
            self.current_rest = rest
            self.current_error = err
            self.tapper.update_cadence(hold, rest, brake)

            if info["ring_r"] is not None:
                self.reel_history.append((t_now - self.t_reel_start, info["ring_r"], hold, rest))

        # ------------------- ESTADO: WAIT_GUARDAR -------------------
        elif self.state == "WAIT_GUARDAR":
            elapsed = t_now - self.t_state
            found = False
            score = 0.0
            if self.guardar_detector and guardar_bgr is not None:
                found, score, _ = self.guardar_detector.detect(guardar_bgr)

            if found:
                print(f"[BOT] >>> Prompt '[E] Guardar Peixe' detectado na tela (score={score:.2f})! Pressionando E...")
                self.input_mgr.trigger_catch()
                self._transition_to("COOLDOWN")
            elif elapsed >= self.cfg["safety"].get("guardar_timeout_s", 3.5):
                print("[BOT] >>> Tempo limite aguardando prompt: pressionando 'E' por segurança...")
                self.input_mgr.trigger_catch()
                self._transition_to("COOLDOWN")

        # ------------------- ESTADO: COOLDOWN -------------------
        elif self.state == "COOLDOWN":
            elapsed = t_now - self.t_state
            # Espera sumir a interface da tela antes de retornar para IDLE
            if elapsed >= self.cfg["safety"]["cooldown_s"] and not info["present"]:
                if self.cfg["keys"]["auto_recast"]:
                    print("[BOT] Auto-recast ativado: Pressionando 'E' para arremessar a vara...")
                    self.input_mgr.trigger_catch()
                    time.sleep(0.5)
                self._transition_to("IDLE")


# ----------------------------------------------------------------------------
# RENDERIZADOR HUD (Interface de diagnóstico visual em tempo real)
# ----------------------------------------------------------------------------
def render_hud(bot, frame_bgr, fps):
    info = bot.current_info
    k = 3  # Escala de ampliação
    big = cv2.resize(frame_bgr, None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST)
    h_big, w_big = big.shape[:2]

    cx = int(info["cx"] * k) if info else int(w_big // 2)
    cy = int(info["cy"] * k) if info else int(h_big // 2)
    r_disc = int(bot.analyzer.disc_r * k)

    # 1. Círculo do disco esperado (branco)
    cv2.circle(big, (cx, cy), r_disc, (255, 255, 255), 1)

    # 2. Círculo alvo da cadência (ciano pontilhado/fino)
    r_target = int(bot.cadence_ctrl.target_r * k)
    cv2.circle(big, (cx, cy), r_target, (255, 255, 0), 1)

    # 3. Anel medido em tempo real (magenta)
    if info and info["ring_r"]:
        r_measured = int(info["ring_r"] * k)
        cv2.circle(big, (cx, cy), r_measured, (255, 0, 255), 2)

    # 4. Indicador de check de vitória no núcleo (verde)
    if info and info["is_caught"]:
        cv2.circle(big, (cx, cy), int(r_disc * 0.45), (0, 255, 0), -1)

    # Painel lateral de status
    panel_w = 340
    panel = np.zeros((h_big, panel_w, 3), np.uint8)

    status_color = (0, 255, 0) if bot.state == "REELING" else (220, 220, 220)
    if bot.state == "CAUGHT":
        status_color = (0, 255, 255)

    ring_str = f"{info['ring_r']:.1f} px" if (info and info["ring_r"]) else "---"
    target_str = f"{bot.cadence_ctrl.target_r:.1f} px"

    lines = [
        f"ESTADO   : {bot.state}",
        f"ARMADO   : {'SIM' if bot.armed else 'NAO (F7)'}",
        f"DISCO    : {'SIM' if (info and info['present']) else 'NAO'}",
        f"ANEL     : {ring_str} (Alvo: {target_str})",
        f"ERRO     : {bot.current_error:+.1f} px",
        f"CADENCIA : {bot.current_hold*1000:.0f}ms / {bot.current_rest*1000:.0f}ms",
        f"TOQUES   : {bot.tapper.taps}",
        f"CHECK PX : {info['check_px'] if info else 0}",
        f"CAPTURAS : {bot.session_catches}",
        f"FPS      : {fps:.0f}",
        "",
        "F6 = Iniciar/Pausar | F7 = Armar",
        "ESC = Encerrar com seguranca",
    ]

    for idx, line in enumerate(lines):
        y_pos = 22 + idx * 20
        col = status_color if idx == 0 else (220, 220, 220)
        cv2.putText(panel, line, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.44, col, 1, cv2.LINE_AA)

    return np.hstack([big, panel])


# ----------------------------------------------------------------------------
# TESTE OFFLINE COM IMAGENS DE REFERÊNCIA
# ----------------------------------------------------------------------------
def run_offline_test():
    """Valida o analisador com as duas imagens enviadas pelo usuário."""
    print("=================================================================")
    print("EXECUTANDO TESTE OFFLINE COM IMAGENS DE REFERÊNCIA")
    print("=================================================================")
    cfg = load_config()
    analyzer = CircleAnalyzer(cfg)

    img_start_path = os.path.join(BASE_DIR, "WhatsApp Image 2026-10-16 at 22.03.43.jpeg")
    img_end_path = os.path.join(BASE_DIR, "WhatsApp Image 2026-10-16 at 22.10.27.jpeg")

    # 1. Teste da Imagem 1 (Início do Minigame Circular)
    if os.path.exists(img_start_path):
        img1 = cv2.imread(img_start_path)
        # Ajusta geometria simulada baseada nas dimensões da imagem cropada
        analyzer.update_geometry(
            region={"left": 0, "top": 0, "width": img1.shape[1], "height": img1.shape[0]},
            cx=img1.shape[1] / 2.0,
            cy=img1.shape[0] / 2.0,
            r=33.0
        )

        res1 = analyzer.analyze(img1)
        print(f"\n[TESTE 1] Imagem de Início ({os.path.basename(img_start_path)}):")
        print(f"  - Disco Presente       : {res1['present']} (borda escura={res1['rim_dark']:.2f})")
        print(f"  - Raio do Anel Medido  : {res1['ring_r']:.1f} px (pixels={res1['n_ring']})")
        print(f"  - Check de Conclusão   : {res1['is_caught']} (check_px={res1['check_px']})")
        assert res1["present"], "Falha: O disco deveria ter sido detectado na imagem de início!"
        assert not res1["is_caught"], "Falha: Não deveria indicar vitória na imagem de início!"
        print("  -> SUCESSO: Gatilho de início reconhecido com perfeição!")

    # 2. Teste da Imagem 2 (Fim do Minigame / FISHING.CAUGHT)
    if os.path.exists(img_end_path):
        img2 = cv2.imread(img_end_path)
        analyzer.update_geometry(
            region={"left": 0, "top": 0, "width": 100, "height": img2.shape[0]},
            cx=50.5,
            cy=54.5,
            r=38.0
        )

        res2 = analyzer.analyze(img2[:, :100])
        print(f"\n[TESTE 2] Imagem de Fim ({os.path.basename(img_end_path)}):")
        print(f"  - Disco Presente       : {res2['present']}")
        print(f"  - Check de Conclusão   : {res2['is_caught']} (check_px={res2['check_px']})")
        assert res2["is_caught"], "Falha: O check de vitória deveria ter sido detectado!"
        print("  -> SUCESSO: Gatilho de vitória e guarda de peixe ('E') reconhecido com perfeição!")

    # 3. Teste da Imagem 3 (Prompt '[E] Guardar Peixe' - WhatsApp Image 22.29.33)
    img_guardar_path = os.path.join(BASE_DIR, "WhatsApp Image 2026-10-16 at 22.29.33.jpeg")
    if os.path.exists(img_guardar_path):
        img3 = cv2.imread(img_guardar_path)
        detector = GuardarDetector(cfg)
        found3, score3, loc3 = detector.detect(img3)
        print(f"\n[TESTE 3] Imagem de Guardar Peixe ({os.path.basename(img_guardar_path)}):")
        print(f"  - Prompt Detectado     : {found3} (score={score3:.4f})")
        assert found3, "Falha: O prompt '[E] Guardar Peixe' deveria ter sido detectado!"
        print("  -> SUCESSO: Gatilho de pressionar 'E' no momento exato reconhecido com perfeição!")

    print("\n[OK] Todos os testes offline foram validados com êxito!")


# ----------------------------------------------------------------------------
# LOOP PRINCIPAL DO PROGRAMA
# ----------------------------------------------------------------------------
def main():
    if "--test" in sys.argv:
        run_offline_test()
        return

    print("=================================================================")
    print(" PESCA AUTOMÁTICA INTELIGENTE — MINIGAME CIRCULAR")
    print("=================================================================")

    # Otimização de precisão de timer no Windows
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

    cfg = load_config()
    guardar_detector = GuardarDetector(cfg)
    input_mgr = InputManager(
        backend=cfg["keys"]["input_backend"],
        reel_key=cfg["keys"]["reel_key"],
        catch_key=cfg["keys"]["catch_key"],
        catch_hold=cfg["keys"]["catch_key_hold"],
    )

    tapper = AdaptiveTapper(
        input_mgr=input_mgr,
        base_hold=cfg["cadence"]["base_hold"],
        base_rest=cfg["cadence"]["base_rest"],
    )
    tapper.start()

    analyzer = CircleAnalyzer(cfg)
    bot = FishingBot(cfg, input_mgr, tapper, analyzer, guardar_detector=guardar_detector)

    # Hotkeys
    stop_event = threading.Event()
    try:
        import keyboard
        keyboard.add_hotkey("f6", lambda: (
            bot.set_armed(not bot.armed),
            print(f"[HOTKEY F6] Bot {'ATIVADO' if bot.armed else 'PAUSADO'}")
        ))
        keyboard.add_hotkey("f7", lambda: (
            bot.set_armed(not bot.armed),
            print(f"[HOTKEY F7] Armado: {bot.armed}")
        ))
        keyboard.add_hotkey("esc", stop_event.set)
        print("[HOTKEYS] F6 = Pausar/Iniciar | F7 = Alternar Armado | ESC = Sair")
    except Exception as e:
        print(f"[AVISO] Não foi possível registrar hotkeys globais do 'keyboard': {e}")

    # Configuração de captura de tela (mss)
    try:
        import mss
    except ImportError:
        sys.exit("[ERRO] Biblioteca 'mss' não instalada. Execute: pip install mss")

    disc_region = cfg["screen"]["disc_region"]
    guardar_region = cfg["screen"]["guardar_region"]

    def _union(a, b):
        l, t = min(a["left"], b["left"]), min(a["top"], b["top"])
        r = max(a["left"] + a["width"], b["left"] + b["width"])
        b_ = max(a["top"] + a["height"], b["top"] + b["height"])
        return {"left": l, "top": t, "width": r - l, "height": b_ - t}

    capture_roi = _union(disc_region, guardar_region)
    dx = disc_region["left"] - capture_roi["left"]
    dy = disc_region["top"] - capture_roi["top"]
    gx = guardar_region["left"] - capture_roi["left"]
    gy = guardar_region["top"] - capture_roi["top"]

    cv2.namedWindow("Pesca Inteligente")
    cv2.moveWindow("Pesca Inteligente", 1200, 50)

    fps, n_fps, t_fps = 0.0, 0, time.perf_counter()
    last_ui_update = 0.0

    print(f"[INFO] Monitorando tela (região unificada: {capture_roi}). Dê foco ao jogo!")

    try:
        with mss.mss() as sct:
            while not stop_event.is_set():
                t_now = time.perf_counter()
                cap = np.array(sct.grab(capture_roi))[:, :, :3]
                disc_bgr = cap[dy:dy + disc_region["height"], dx:dx + disc_region["width"]]
                guardar_bgr = cap[gy:gy + guardar_region["height"], gx:gx + guardar_region["width"]]

                bot.step(disc_bgr, t_now, guardar_bgr)

                # Cálculo de FPS
                n_fps += 1
                if t_now - t_fps >= 1.0:
                    fps = n_fps / (t_now - t_fps)
                    n_fps = 0
                    t_fps = t_now

                # Atualização do HUD (intervalo de 30ms para não consumir CPU desnecessária)
                if t_now - last_ui_update >= 0.030:
                    hud = render_hud(bot, disc_bgr, fps)
                    cv2.imshow("Pesca Inteligente", hud)
                    key = cv2.waitKey(1) & 0xFF
                    if key == 27:  # ESC na janela do OpenCV
                        break
                    last_ui_update = t_now

    except KeyboardInterrupt:
        print("\n[INTERROMPIDO] Encerrando pelo terminal...")
    finally:
        tapper.stop_taps()
        tapper.quit.set()
        input_mgr.force_release_all()
        cv2.destroyAllWindows()
        print("[FINALIZADO] Teclas liberadas e macro encerrado com sucesso.")


if __name__ == "__main__":
    main()
