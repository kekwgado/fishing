"""
================================================================================
Módulo de Configuração Dinâmica, Auto-Resolução e Detecção de Guardar Peixe
================================================================================
Responsabilidades:
  1. Identificação automática da resolução do monitor e sistema.
  2. Cálculo proporcional e sincronização com 'config.json' (persistência).
  3. Detecção em tempo real do prompt '[E] Guardar Peixe'
     (referência: 'WhatsApp Image 2026-10-16 at 22.29.33.jpeg').
================================================================================
"""

import datetime
import json
import os
import time

import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
TEMPLATE_GUARDAR_PATH = os.path.join(BASE_DIR, "template_guardar.png")
IMG_REF_GUARDAR = os.path.join(BASE_DIR, "WhatsApp Image 2026-10-16 at 22.29.33.jpeg")

# Configuração Padrão Base (1920x1080)
DEFAULT_CONFIG = {
    "system_profile": {
        "screen_width": 1920,
        "screen_height": 1080,
        "scale_x": 1.0,
        "scale_y": 1.0,
        "auto_detected": True,
        "updated_at": "",
    },
    "screen": {
        # Minigame 1: Barra Cinza Vertical
        "bar_region": {
            "left": 993,
            "top": 475,
            "width": 28,
            "height": 220,
        },
        # Minigame 2: Disco Circular
        "disc_region": {
            "left": 955,
            "top": 400,
            "width": 144,
            "height": 144,
        },
        "disc_cx": 1026.8,
        "disc_cy": 472.0,
        "disc_r": 50.0,
        # Stage 3: Região de Busca do Prompt '[E] Guardar Peixe'
        "guardar_region": {
            "left": 720,
            "top": 480,
            "width": 480,
            "height": 360,
        },
    },
    "cadence": {
        "base_hold": 0.108,
        "base_rest": 0.145,
        "min_hold": 0.080,
        "max_hold": 0.125,
        "min_rest": 0.050,
        "max_rest": 0.320,
        "target_ratio": 0.50,
        "kp_rest": 0.0055,
        "kd_rest": 0.0025,
        "kp_hold": 0.0010,
        "invert_tension": False,
    },
    "detection": {
        "disc_dark_v": 75,
        "disc_rim_dark_frac": 0.60,
        "ring_v_min": 75,
        "ring_s_min": 10,
        "ring_s_max": 220,
        "ring_h_max": 35,
        "ring_h_min2": 160,
        "ring_min_px": 25,
        "check_min_px": 80,
        "check_stable_frames": 2,
        "disc_stable_frames": 4,
        "guardar_threshold": 0.65,
    },
    "keys": {
        "reel_key": "enter",
        "catch_key": "e",
        "catch_key_hold": 0.100,
        "input_backend": "pydirectinput",
        "auto_recast": False,
        "recast_delay": 2.0,
    },
    "safety": {
        "max_reel_s": 120.0,
        "reel_gone_s": 1.2,
        "guardar_timeout_s": 3.5,
        "cooldown_s": 2.0,
    },
}


def detect_screen_resolution():
    """Identifica automaticamente a resolução do monitor primário."""
    # 1. Tenta mss (captura nativa do sistema)
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1]
            return int(mon["width"]), int(mon["height"])
    except Exception:
        pass

    # 2. Tenta Windows API nativa
    try:
        import ctypes
        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
        w = int(user32.GetSystemMetrics(0))
        h = int(user32.GetSystemMetrics(1))
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass

    # Fallback padrão seguro
    return 1920, 1080


def load_and_sync_config(force_recalc=False):
    """
    Carrega o arquivo config.json.
    Verifica se a resolução atual coincide com os dados salvos:
      - Se coincidir: carrega os dados persistidos imediatamente sem recalcular nada.
      - Se a resolução mudou ou for a 1ª execução: calcula proporcionalmente e salva
        as configurações no config.json para persistência.
    """
    screen_w, screen_h = detect_screen_resolution()
    cfg = DEFAULT_CONFIG.copy()

    file_exists = os.path.exists(CONFIG_FILE)
    if file_exists:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for sec, vals in loaded.items():
                    if sec in cfg and isinstance(vals, dict):
                        cfg[sec].update(vals)
                    else:
                        cfg[sec] = vals
        except Exception as e:
            print(f"[AVISO] Erro ao ler '{CONFIG_FILE}': {e}. Usando padrões.")

    profile = cfg.get("system_profile", {})
    cached_w = profile.get("screen_width")
    cached_h = profile.get("screen_height")

    # Se a resolução persistida já corresponde à atual, reutiliza os dados salvos
    if not force_recalc and cached_w == screen_w and cached_h == screen_h:
        print(f"[CONFIG] Resolução confirmada: {screen_w}x{screen_h} (usando dados persistidos em config.json).")
        return cfg

    # Resolução diferente detectada ou primeira execução: calcular e persistir
    print(f"[CONFIG] Detectada resolução de tela: {screen_w}x{screen_h} (perfil salvo: {cached_w}x{cached_h}).")
    print("[CONFIG] Atualizando coordenadas e persistindo no 'config.json'...")

    sx = screen_w / 1920.0
    sy = screen_h / 1080.0
    sr = min(sx, sy)

    # 1. Minigame 1: Barra Cinza
    cfg["screen"]["bar_region"] = {
        "left": int(round(993 * sx)),
        "top": int(round(475 * sy)),
        "width": max(20, int(round(28 * sx))),
        "height": int(round(220 * sy)),
    }

    # 2. Minigame 2: Disco Circular
    cfg["screen"]["disc_region"] = {
        "left": int(round(955 * sx)),
        "top": int(round(400 * sy)),
        "width": int(round(144 * sx)),
        "height": int(round(144 * sy)),
    }
    cfg["screen"]["disc_cx"] = round(1026.8 * sx, 1)
    cfg["screen"]["disc_cy"] = round(472.0 * sy, 1)
    cfg["screen"]["disc_r"] = round(50.0 * sr, 1)

    # 3. Stage 3: Prompt de Guardar Peixe
    cfg["screen"]["guardar_region"] = {
        "left": int(round(720 * sx)),
        "top": int(round(480 * sy)),
        "width": int(round(480 * sx)),
        "height": int(round(360 * sy)),
    }

    # Atualiza o perfil do sistema
    cfg["system_profile"] = {
        "screen_width": screen_w,
        "screen_height": screen_h,
        "scale_x": round(sx, 4),
        "scale_y": round(sy, 4),
        "auto_detected": True,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Persiste no config.json
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        print(f"[CONFIG] Configurações de {screen_w}x{screen_h} persistidas com sucesso em '{CONFIG_FILE}'.")
    except Exception as e:
        print(f"[AVISO] Falha ao persistir em '{CONFIG_FILE}': {e}")

    return cfg


# ----------------------------------------------------------------------------
# DETECTOR DO PROMPT '[E] Guardar Peixe' (WhatsApp Image 22.29.33)
# ----------------------------------------------------------------------------
class GuardarDetector:
    """Detecta o surgimento do prompt na tela indicando a hora exata de apertar 'E'."""

    def __init__(self, cfg=None):
        self.cfg = cfg or load_and_sync_config()
        self.threshold = self.cfg["detection"].get("guardar_threshold", 0.65)
        self.template = None
        self._load_template()

    def _load_template(self):
        # Tenta carregar o template direto se existir
        if os.path.exists(TEMPLATE_GUARDAR_PATH):
            self.template = cv2.imread(TEMPLATE_GUARDAR_PATH)
        elif os.path.exists(IMG_REF_GUARDAR):
            full_img = cv2.imread(IMG_REF_GUARDAR)
            if full_img is not None:
                # Extrai o badge [E] Guardar Peixe
                self.template = full_img[:, :160]
                try:
                    cv2.imwrite(TEMPLATE_GUARDAR_PATH, self.template)
                except Exception:
                    pass

        if self.template is not None:
            self.th, self.tw = self.template.shape[:2]
        else:
            print("[AVISO] Template '[E] Guardar Peixe' não pôde ser carregado.")

    def detect(self, search_bgr):
        """
        Analisa a região de busca e retorna (encontrado, score, (x, y)).
        Usa template matching normalizado e análise de cor da letra 'E' com fundo escuro.
        """
        if self.template is None or search_bgr is None:
            return False, 0.0, None

        sh, sw = search_bgr.shape[:2]
        if sh < self.th or sw < self.tw:
            return False, 0.0, None

        # Template Matching Normalizado (invariante a iluminação)
        res = cv2.matchTemplate(search_bgr, self.template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val >= self.threshold:
            return True, float(max_val), max_loc

        # Verificação secundária por características de cor caso a pontuação esteja próxima
        # Badge escuro (V < 40) com letra branca interna (V > 180, S < 40)
        hsv = cv2.cvtColor(search_bgr, cv2.COLOR_BGR2HSV)
        white_pixels = (hsv[:, :, 1] < 40) & (hsv[:, :, 2] > 180)
        dark_pixels = hsv[:, :, 2] < 40

        # Se houver estrutura de texto branco envolto por badge escuro
        if white_pixels.sum() >= 150 and dark_pixels.sum() >= 400 and max_val >= (self.threshold - 0.15):
            return True, float(max_val), max_loc

        return False, float(max_val), max_loc
